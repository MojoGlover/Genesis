"""
Reddit Crawler — Karma KaMillion team.

Proving Ground agent. Runs standalone via CLI/cron, not wired to a
Coordinator yet (see team's Proving Ground rule: stress-test solo first).

Pulls recent posts from a rotating list of subreddits (Reddit's public
new.json listing needs no OAuth for read-only access), scores them by
comment velocity, upvote ratio, and repeated-phrase clustering across
titles, and emits the top N as a ranked JSON list.

Run with: python main.py [--dry-run] [--config config.yaml] [--output out.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parent

logger = logging.getLogger("reddit_crawler")
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


# ── Structured logging (Chronicle-compatible schema) ─────────────────────────
# Same field names Chronicle's ingest expects (kind/actor/target/object/
# action/outcome/detail) so these lines can be forwarded verbatim once this
# agent is wired to a Coordinator. Not POSTed anywhere yet — standalone only.

def log_event(*, kind: str, action: str, outcome: str = "ok", target: str = "",
              object: str = "", detail: str = "", duration_ms: int | None = None) -> None:
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "actor": "reddit_crawler",
        "target": target,
        "object": object,
        "action": action,
        "outcome": outcome,
        "detail": detail[:200],
        "duration_ms": duration_ms,
    }
    logger.info(json.dumps(event))


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or (ROOT / "config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    if os.environ.get("REDDIT_USER_AGENT"):
        config["reddit"]["user_agent"] = os.environ["REDDIT_USER_AGENT"]
    if os.environ.get("OUTPUT_PATH"):
        config["output"]["path"] = os.environ["OUTPUT_PATH"]
    return config


# ── Accountant gate (local until Accountant is online) ───────────────────────
# Reddit free tier: 100 req/min, 1000 req/10min. Accountant is the grid's
# intended quota authority but isn't built yet, so this tracks its own
# sliding windows in-process. Swap check()'s body for a call to Accountant's
# /spend/check once that service exists — don't hand-maintain this forever.

class QuotaGate:
    def __init__(self, per_minute: int, per_10min: int, warn_threshold_pct: int = 80) -> None:
        self.per_minute = per_minute
        self.per_10min = per_10min
        self.warn_threshold_pct = warn_threshold_pct
        self._minute_window: deque[float] = deque()
        self._ten_min_window: deque[float] = deque()

    def _prune(self, window: deque[float], span_seconds: float, now: float) -> None:
        while window and now - window[0] > span_seconds:
            window.popleft()

    def check(self) -> None:
        """Block if headroom is exhausted; log a warning as headroom gets tight."""
        now = time.monotonic()
        self._prune(self._minute_window, 60.0, now)
        self._prune(self._ten_min_window, 600.0, now)

        minute_pct = len(self._minute_window) / self.per_minute * 100
        ten_min_pct = len(self._ten_min_window) / self.per_10min * 100
        if minute_pct >= self.warn_threshold_pct or ten_min_pct >= self.warn_threshold_pct:
            log_event(kind="quota", action="check", outcome="warn",
                       target="reddit_api",
                       detail=f"minute={minute_pct:.0f}% ten_min={ten_min_pct:.0f}%")

        if len(self._minute_window) >= self.per_minute:
            sleep_for = 60.0 - (now - self._minute_window[0])
            if sleep_for > 0:
                log_event(kind="quota", action="throttle", outcome="ok",
                           target="reddit_api", detail=f"sleeping {sleep_for:.1f}s (per-minute cap)")
                time.sleep(sleep_for)
        if len(self._ten_min_window) >= self.per_10min:
            sleep_for = 600.0 - (now - self._ten_min_window[0])
            if sleep_for > 0:
                log_event(kind="quota", action="throttle", outcome="ok",
                           target="reddit_api", detail=f"sleeping {sleep_for:.1f}s (10-min cap)")
                time.sleep(sleep_for)

    def record(self) -> None:
        now = time.monotonic()
        self._minute_window.append(now)
        self._ten_min_window.append(now)


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_subreddit(sub: str, config: dict[str, Any], quota_gate: QuotaGate,
                     client: httpx.Client) -> list[dict[str, Any]]:
    listing = config["reddit"]["listing"]
    limit = config["reddit"]["posts_per_subreddit"]
    url = f"https://www.reddit.com/r/{sub}/{listing}.json"
    quota_gate.check()
    resp = client.get(url, params={"limit": limit, "raw_json": 1},
                       headers={"User-Agent": config["reddit"]["user_agent"]}, timeout=10.0)
    quota_gate.record()
    resp.raise_for_status()
    children = resp.json()["data"]["children"]
    return [c["data"] for c in children]


# ── Scoring ───────────────────────────────────────────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "is",
    "was", "am", "are", "be", "with", "at", "by", "my", "me", "i", "it", "this",
    "that", "just", "so", "not", "you", "your", "im", "its",
}


def significant_words(title: str) -> set[str]:
    words = re.findall(r"[a-z']+", title.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_posts(posts: list[dict[str, Any]], threshold: float) -> list[int]:
    """Union-find over title word-sets. Returns each post's cluster size
    (including itself) — repeated complaints phrased differently still cluster."""
    word_sets = [significant_words(p.get("title", "")) for p in posts]
    n = len(posts)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(word_sets[i], word_sets[j]) >= threshold:
                union(i, j)

    cluster_ids = [find(i) for i in range(n)]
    sizes: dict[int, int] = {}
    for cid in cluster_ids:
        sizes[cid] = sizes.get(cid, 0) + 1
    return [sizes[cid] for cid in cluster_ids]


def compute_age_hours(created_utc: float, now: float | None = None) -> float:
    now = now if now is not None else time.time()
    return max((now - created_utc) / 3600.0, 0.0)


def filter_recent(posts: list[dict[str, Any]], max_age_hours: float,
                   now: float | None = None) -> list[dict[str, Any]]:
    return [p for p in posts if compute_age_hours(p["created_utc"], now) <= max_age_hours]


def score_posts(posts: list[dict[str, Any]], config: dict[str, Any],
                 now: float | None = None) -> list[dict[str, Any]]:
    scoring = config["scoring"]
    threshold = scoring["phrase_cluster_jaccard_threshold"]
    cluster_sizes = cluster_posts(posts, threshold)

    scored = []
    for post, cluster_size in zip(posts, cluster_sizes):
        age_hours = compute_age_hours(post["created_utc"], now)
        comment_velocity = post.get("num_comments", 0) / max(age_hours, 0.25)
        upvote_ratio = post.get("upvote_ratio", 0.0)
        repeat_signal = cluster_size - 1

        total_score = (
            scoring["weight_comment_velocity"] * comment_velocity
            + scoring["weight_upvote_ratio"] * upvote_ratio
            + scoring["weight_repeat_signal"] * repeat_signal
        )

        scored.append({
            "subreddit": post.get("subreddit", ""),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "title": post.get("title", ""),
            "score": round(total_score, 3),
            "comment_velocity": round(comment_velocity, 3),
            "upvote_ratio": upvote_ratio,
            "repeat_cluster_size": cluster_size,
            "top_snippet": (post.get("selftext") or post.get("title", ""))[:280],
            "created_utc": post.get("created_utc"),
            "age_hours": round(age_hours, 2),
        })
    return scored


def rank_top(scored_posts: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    return sorted(scored_posts, key=lambda p: p["score"], reverse=True)[:top_n]


# ── Dry-run fixture ───────────────────────────────────────────────────────────

def _dry_run_posts(config: dict[str, Any]) -> list[dict[str, Any]]:
    now = time.time()
    subs = config["reddit"]["subreddits"]
    sample_titles = [
        "My manager screamed at me in front of customers and I quit on the spot",
        "Boss yelled at me in front of everyone and I walked out",
        "TIFU by replying-all to the entire company with a complaint",
        "My roommate ate my labeled food again and denied it",
        "AITA for telling my neighbor to turn down his music at 3am",
        "Customer service hung up on me three times today",
        "My neighbor keeps parking in my spot and won't stop",
    ]
    posts = []
    for i, (sub, title) in enumerate(zip(subs, sample_titles)):
        posts.append({
            "subreddit": sub,
            "title": title,
            "selftext": f"Sample dry-run body text for post {i}.",
            "permalink": f"/r/{sub}/comments/sample{i}/",
            "created_utc": now - (i + 1) * 3600,
            "num_comments": 20 + i * 15,
            "upvote_ratio": 0.7 + (i % 3) * 0.1,
        })
    return posts


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(config: dict[str, Any], dry_run: bool = False) -> list[dict[str, Any]]:
    if dry_run:
        log_event(kind="crawl", action="run", outcome="ok", detail="dry-run: using fixture data")
        all_posts = _dry_run_posts(config)
    else:
        quota_gate = QuotaGate(config["quota"]["requests_per_minute"],
                                config["quota"]["requests_per_10min"],
                                config["quota"]["warn_threshold_pct"])
        all_posts = []
        with httpx.Client() as client:
            for sub in config["reddit"]["subreddits"]:
                try:
                    posts = fetch_subreddit(sub, config, quota_gate, client)
                    for p in posts:
                        p["subreddit"] = sub
                    all_posts.extend(posts)
                    log_event(kind="crawl", action="fetch", outcome="ok",
                              target="reddit_api", object=f"subreddit:{sub}",
                              detail=f"{len(posts)} posts")
                except Exception as exc:
                    log_event(kind="crawl", action="fetch", outcome="error",
                              target="reddit_api", object=f"subreddit:{sub}", detail=str(exc))

    recent = filter_recent(all_posts, config["reddit"]["max_age_hours"])
    scored = score_posts(recent, config)
    top = rank_top(scored, config["output"]["top_n"])
    log_event(kind="crawl", action="rank", outcome="ok",
              detail=f"{len(all_posts)} fetched, {len(recent)} recent, top {len(top)} returned")
    return top


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Reddit Crawler — Karma KaMillion")
    parser.add_argument("--dry-run", action="store_true",
                         help="Use built-in fixture data instead of calling Reddit")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON output here too")
    args = parser.parse_args()

    config = load_config(args.config)
    top = run_pipeline(config, dry_run=args.dry_run)

    output_json = json.dumps(top, indent=2)
    print(output_json)

    output_path = args.output or config["output"].get("path")
    if output_path:
        Path(output_path).write_text(output_json)
        log_event(kind="crawl", action="write", outcome="ok", target=str(output_path))


if __name__ == "__main__":
    main()
