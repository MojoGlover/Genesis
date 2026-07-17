"""
YouTube Comments Crawler — Karma KaMillion team.

Proving Ground agent. Runs standalone via CLI/cron, not wired to a
Coordinator yet (see team's Proving Ground rule: stress-test solo first).

Refreshes against a configurable channel watchlist, pulls each channel's
recent uploads and their top comment threads, scores threads by reply depth
and negative-sentiment intensity (a short angry thread should outrank a
long lukewarm one), and emits the top N as a ranked JSON list.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

try:
    from zoneinfo import ZoneInfo
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:
    _PACIFIC = None  # tzdata unavailable on this system — fall back to UTC days

ROOT = Path(__file__).resolve().parent
API_BASE = "https://www.googleapis.com/youtube/v3"

logger = logging.getLogger("youtube_crawler")
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
        "actor": "youtube_crawler",
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
    if os.environ.get("OUTPUT_PATH"):
        config["output"]["path"] = os.environ["OUTPUT_PATH"]
    return config


# ── Accountant gate (local until Accountant is online) ───────────────────────
# YouTube Data API v3 free tier: 10,000 units/day, resetting at midnight
# Pacific Time (not UTC — a common gotcha). Accountant is the grid's intended
# quota authority but isn't built yet, so this tracks its own daily budget in
# a small state file. Swap _spend()'s body for a call to Accountant's
# /spend/check once that service exists — don't hand-maintain this forever.

def _today_key(now: float | None = None) -> str:
    now = now if now is not None else time.time()
    dt = datetime.fromtimestamp(now, tz=_PACIFIC or timezone.utc)
    return dt.strftime("%Y-%m-%d")


class QuotaGate:
    def __init__(self, daily_cap: int, warn_threshold_pct: int, state_path: Path) -> None:
        self.daily_cap = daily_cap
        self.warn_threshold_pct = warn_threshold_pct
        self.state_path = state_path
        self._state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        today = _today_key()
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text())
                if state.get("date") == today:
                    return state
            except Exception:
                pass
        return {"date": today, "units_used": 0}

    def _save_state(self) -> None:
        try:
            self.state_path.write_text(json.dumps(self._state))
        except Exception:
            pass  # gate must never crash the crawl over a disk write failure

    @property
    def units_used(self) -> int:
        return self._state["units_used"]

    def headroom_pct(self) -> float:
        return self.units_used / self.daily_cap * 100

    def check(self, units_needed: int) -> bool:
        """Returns False (and logs) if this call would exceed the daily cap."""
        pct = self.headroom_pct()
        if pct >= self.warn_threshold_pct:
            log_event(kind="quota", action="check", outcome="warn",
                       target="youtube_api", detail=f"{pct:.0f}% of daily unit cap used")
        if self.units_used + units_needed > self.daily_cap:
            log_event(kind="quota", action="check", outcome="blocked",
                       target="youtube_api",
                       detail=f"would exceed cap: {self.units_used}+{units_needed} > {self.daily_cap}")
            return False
        return True

    def record(self, units: int) -> None:
        today = _today_key()
        if self._state["date"] != today:
            self._state = {"date": today, "units_used": 0}
        self._state["units_used"] += units
        self._save_state()


# ── Fetch ─────────────────────────────────────────────────────────────────────

def uploads_playlist_id(channel_id: str) -> str:
    """Every channel's "uploads" playlist ID is its channel ID with the
    UC prefix swapped for UU — avoids the 100-unit search.list call just to
    find recent videos (playlistItems.list costs 1 unit instead)."""
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return channel_id


def fetch_recent_videos(channel_id: str, config: dict[str, Any], quota_gate: QuotaGate,
                         client: httpx.Client, api_key: str) -> list[dict[str, Any]]:
    cost = config["quota"]["cost_playlist_items"]
    if not quota_gate.check(cost):
        return []
    playlist_id = uploads_playlist_id(channel_id)
    resp = client.get(f"{API_BASE}/playlistItems", params={
        "part": "snippet", "playlistId": playlist_id,
        "maxResults": config["youtube"]["max_videos_per_channel"],
        "key": api_key,
    }, timeout=10.0)
    quota_gate.record(cost)
    resp.raise_for_status()
    videos = []
    for item in resp.json().get("items", []):
        snippet = item["snippet"]
        videos.append({
            "video_id": snippet["resourceId"]["videoId"],
            "video_title": snippet["title"],
            "channel_id": channel_id,
            "published_at": snippet["publishedAt"],
        })
    return videos


def fetch_comment_threads(video: dict[str, Any], config: dict[str, Any], quota_gate: QuotaGate,
                           client: httpx.Client, api_key: str) -> list[dict[str, Any]]:
    cost = config["quota"]["cost_comment_threads"]
    if not quota_gate.check(cost):
        return []
    resp = client.get(f"{API_BASE}/commentThreads", params={
        "part": "snippet", "videoId": video["video_id"],
        "order": config["youtube"]["comment_order"],
        "maxResults": config["youtube"]["max_comments_per_video"],
        "textFormat": "plainText", "key": api_key,
    }, timeout=10.0)
    quota_gate.record(cost)
    resp.raise_for_status()
    threads = []
    for item in resp.json().get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        threads.append({
            "comment_id": item["id"],
            "text": top["textDisplay"],
            "reply_count": item["snippet"].get("totalReplyCount", 0),
            "video_id": video["video_id"],
            "video_title": video["video_title"],
            "channel_id": video["channel_id"],
        })
    return threads


# ── Sentiment (lexicon-based — no heavyweight NLP dependency) ────────────────

_NEGATIVE_WORDS = {
    "hate", "hated", "angry", "furious", "terrible", "awful", "worst", "garbage",
    "trash", "scam", "broken", "disgusting", "pathetic", "ridiculous", "useless",
    "disappointed", "disappointing", "annoying", "annoyed", "rip", "ripoff",
    "unacceptable", "horrible", "sucks", "sucked", "cancel", "cancelled",
    "refund", "complaint", "furious", "outraged", "livid", "scammed", "lied",
    "lies", "liar", "fraud", "never", "worse", "fail", "failed", "failure",
}
_POSITIVE_WORDS = {
    "love", "loved", "great", "amazing", "excellent", "best", "awesome",
    "fantastic", "wonderful", "happy", "thanks", "thank", "perfect", "good",
    "helpful", "recommend", "brilliant", "impressive",
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def negativity(text: str) -> float:
    """Magnitude of negative sentiment in [0, 1]. Positive words offset it —
    a comment with both isn't a clean complaint signal."""
    words = _tokenize(text)
    if not words:
        return 0.0
    neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
    pos = sum(1 for w in words if w in _POSITIVE_WORDS)
    raw = (neg - pos) / len(words)
    return max(0.0, min(raw * 5, 1.0))  # scaled + clamped; lexicon hits are sparse per comment


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_threads(threads: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    scoring = config["scoring"]
    cap = scoring["reply_depth_cap"]
    scored = []
    for t in threads:
        reply_norm = min(t["reply_count"], cap) / cap
        neg = negativity(t["text"])
        total_score = (
            scoring["weight_reply_depth"] * reply_norm
            + scoring["weight_sentiment"] * neg
        )
        scored.append({
            "video_id": t["video_id"],
            "video_title": t["video_title"],
            "channel_id": t["channel_id"],
            "comment_id": t["comment_id"],
            "complaint_text": t["text"][:280],
            "reply_count": t["reply_count"],
            "sentiment_score": round(neg, 3),
            "score": round(total_score, 3),
            "url": f"https://www.youtube.com/watch?v={t['video_id']}&lc={t['comment_id']}",
        })
    return scored


def rank_top(scored_threads: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    return sorted(scored_threads, key=lambda t: t["score"], reverse=True)[:top_n]


# ── Dry-run fixture ───────────────────────────────────────────────────────────

def _dry_run_threads(config: dict[str, Any]) -> list[dict[str, Any]]:
    channel = config["youtube"]["watchlist"][0]
    samples = [
        ("This is absolutely the worst customer service I have ever experienced, total scam", 42),
        ("Great video, thanks for sharing this, really helpful!", 3),
        ("Broken on arrival, useless product, complete ripoff, never buying again", 90),
        ("cool", 0),
        ("Disappointed and annoyed, this is unacceptable and pathetic support", 15),
    ]
    threads = []
    for i, (text, replies) in enumerate(samples):
        threads.append({
            "comment_id": f"sample_comment_{i}",
            "text": text,
            "reply_count": replies,
            "video_id": f"sample_video_{i % 2}",
            "video_title": f"Sample Video {i % 2}",
            "channel_id": channel,
        })
    return threads


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(config: dict[str, Any], dry_run: bool = False) -> list[dict[str, Any]]:
    if dry_run:
        log_event(kind="crawl", action="run", outcome="ok", detail="dry-run: using fixture data")
        all_threads = _dry_run_threads(config)
    else:
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        state_path = ROOT / config["quota"]["state_path"]
        quota_gate = QuotaGate(config["quota"]["daily_unit_cap"],
                                config["quota"]["warn_threshold_pct"], state_path)
        all_threads = []
        with httpx.Client() as client:
            for channel_id in config["youtube"]["watchlist"]:
                try:
                    videos = fetch_recent_videos(channel_id, config, quota_gate, client, api_key)
                    log_event(kind="crawl", action="fetch_videos", outcome="ok",
                              target="youtube_api", object=f"channel:{channel_id}",
                              detail=f"{len(videos)} videos")
                    for video in videos:
                        threads = fetch_comment_threads(video, config, quota_gate, client, api_key)
                        all_threads.extend(threads)
                except Exception as exc:
                    log_event(kind="crawl", action="fetch", outcome="error",
                              target="youtube_api", object=f"channel:{channel_id}", detail=str(exc))

    scored = score_threads(all_threads, config)
    top = rank_top(scored, config["output"]["top_n"])
    log_event(kind="crawl", action="rank", outcome="ok",
              detail=f"{len(all_threads)} threads scored, top {len(top)} returned")
    return top


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Comments Crawler — Karma KaMillion")
    parser.add_argument("--dry-run", action="store_true",
                         help="Use built-in fixture data instead of calling the YouTube API")
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
