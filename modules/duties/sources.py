"""
sources.py — deterministic intelligence gathering (GENESIS duties module).

Keeps an agent current in its own field by FETCHING from real endpoints, not by
asking a model to "go find new techniques".

WHY THIS MUST BE CODE
---------------------
A fabricated health report is obvious the moment you look at the disk. A
fabricated advisory is not — an invented CVE number with a plausible summary
looks exactly like a real one, and you act on it. Asked to research, a local
model produces confident summaries of work that does not exist.

A fetcher cannot invent an item that was not in the feed. Whether an item
MATTERS is judgment, made afterwards, against items that provably exist.

Sources are free and keyless on purpose: no spend, no API keys, no Accountant
gate (cmptrblk/CLAUDE.md — agents run local; cloud calls need authorization).

Profiles are per-domain. An agent watches its own field: a security agent
drowning in web-framework releases is noise, not intelligence.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

__all__ = ["PROFILES", "scan", "load_seen", "save_seen"]

_UA = "Mozilla/5.0 (compatible; ComputerBlack-agent/1.0)"
_TIMEOUT = 20

PROFILES: dict[str, dict] = {
    "security": {
        "arxiv_categories": ["cs.CR"],
        "arxiv_keywords": [
            "prompt injection", "llm security", "agent security", "jailbreak",
            "adversarial", "supply chain", "credential", "sandbox escape",
        ],
        "github_releases": ["ollama/ollama", "tailscale/tailscale", "nginx/nginx"],
        # Scoped to software this grid actually runs — not all 350k CVEs.
        "nvd_keywords": ["ollama", "nginx", "tailscale", "fastapi", "sqlite"],
    },
    "infrastructure": {
        "arxiv_categories": [],
        "arxiv_keywords": [],
        "github_releases": ["ollama/ollama", "astral-sh/uv", "systemd/systemd"],
        "nvd_keywords": ["systemd", "openssh", "python"],
    },
    "research": {
        "arxiv_categories": ["cs.AI", "cs.LG"],
        "arxiv_keywords": [
            "agent", "tool use", "planning", "evaluation", "benchmark",
            "self-improvement", "curriculum",
        ],
        "github_releases": [],
        "nvd_keywords": [],
    },
}

# CISA's Known Exploited Vulnerabilities feed is the highest-signal free security
# source (things exploited in the wild, not theoretical) but it returns 403 to
# datacenter IPs regardless of user-agent, so it cannot be polled from a VPS.
# Recorded here so nobody re-adds it and wonders why it silently contributes
# nothing.


def _get(url: str) -> bytes | None:
    """Fetch, or None. A source being down must never fail the run."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        print(f"[intel] source unreachable ({url}): {e}", file=sys.stderr)
        return None


def _uid(item: dict) -> str:
    return hashlib.sha256(f"{item['source']}::{item['title']}".encode()).hexdigest()[:16]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000")


def fetch_arxiv(categories, keywords, since_days) -> list[dict]:
    out, cutoff = [], time.time() - since_days * 86400
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for cat in categories:
        raw = _get("http://export.arxiv.org/api/query?"
                   f"search_query=cat:{cat}&sortBy=submittedDate"
                   "&sortOrder=descending&max_results=60")
        if not raw:
            continue
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            continue
        for entry in root.findall("a:entry", ns):
            title = " ".join((entry.findtext("a:title", "", ns) or "").split())
            summary = " ".join((entry.findtext("a:summary", "", ns) or "").split())
            published = entry.findtext("a:published", "", ns) or ""
            try:
                ts = datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = time.time()
            if ts < cutoff:
                continue
            hits = [k for k in keywords if k in f"{title} {summary}".lower()]
            if keywords and not hits:
                continue
            out.append({"source": f"arxiv:{cat}", "title": title,
                        "url": entry.findtext("a:id", "", ns) or "",
                        "published": published, "matched": hits,
                        "summary": summary[:400]})
    return out


def fetch_github_releases(repos, since_days) -> list[dict]:
    out, cutoff = [], time.time() - since_days * 86400
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for repo in repos:
        raw = _get(f"https://github.com/{repo}/releases.atom")
        if not raw:
            continue
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            continue
        for entry in root.findall("a:entry", ns)[:10]:
            updated = entry.findtext("a:updated", "", ns) or ""
            try:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = 0
            if ts < cutoff:
                continue
            link = entry.find("a:link", ns)
            out.append({"source": f"github:{repo}",
                        "title": " ".join((entry.findtext("a:title", "", ns) or "").split()),
                        "url": link.get("href") if link is not None else "",
                        "published": updated, "matched": ["release"], "summary": ""})
    return out


def fetch_nvd(keywords, since_days) -> list[dict]:
    """NVD CVE API — authoritative, free, keyless."""
    out = []
    for kw in keywords:
        raw = _get("https://services.nvd.nist.gov/rest/json/cves/2.0"
                   f"?keywordSearch={kw}&resultsPerPage=20&noRejected"
                   f"&pubStartDate={_iso(time.time() - since_days * 86400)}"
                   f"&pubEndDate={_iso(time.time())}")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for v in data.get("vulnerabilities", []):
            cve = v.get("cve", {})
            desc = next((d["value"] for d in cve.get("descriptions", [])
                         if d.get("lang") == "en"), "")
            sev = ""
            for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                if cve.get("metrics", {}).get(key):
                    sev = cve["metrics"][key][0].get("cvssData", {}).get("baseSeverity", "")
                    break
            out.append({"source": f"nvd:{kw}",
                        "title": f"{cve.get('id', '?')} [{sev or 'unscored'}]",
                        "url": f"https://nvd.nist.gov/vuln/detail/{cve.get('id', '')}",
                        "published": cve.get("published", ""),
                        "matched": [kw] + ([sev.lower()] if sev else []),
                        "summary": desc[:400]})
        time.sleep(1)  # NVD asks for <=5 req/30s unkeyed — be a good citizen
    return out


def load_seen(intel_dir: Path) -> set[str]:
    idx = Path(intel_dir) / "seen.json"
    if not idx.exists():
        return set()
    try:
        return set(json.loads(idx.read_text()).get("seen", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(intel_dir: Path, seen: set[str]) -> None:
    intel_dir = Path(intel_dir)
    intel_dir.mkdir(parents=True, exist_ok=True)
    # Bounded so the index cannot grow without limit on a long-lived agent.
    (intel_dir / "seen.json").write_text(json.dumps({"seen": sorted(seen)[-5000:]}))


def scan(profile: str, data_dir: Path, since_days: int = 7,
         extra: dict | None = None) -> dict:
    """Fetch, dedupe against what's been seen, write NEW items only.

    An agent should be told what CHANGED, not handed the same advisory every
    morning — so the seen-index is the point, not an optimization.
    """
    cfg = dict(PROFILES.get(profile, {}))
    for k, v in (extra or {}).items():  # per-agent additions to a shared profile
        cfg[k] = list(cfg.get(k, [])) + list(v)

    items = (fetch_arxiv(cfg.get("arxiv_categories", []),
                         cfg.get("arxiv_keywords", []), since_days)
             + fetch_github_releases(cfg.get("github_releases", []), since_days)
             + fetch_nvd(cfg.get("nvd_keywords", []), since_days))

    intel_dir = Path(data_dir).expanduser() / "intel"
    seen = load_seen(intel_dir)
    new = [i for i in items if _uid(i) not in seen]
    seen.update(_uid(i) for i in new)
    save_seen(intel_dir, seen)

    report = {
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile": profile,
        "fetched": len(items),
        "new": len(new),
        "items": new,
    }
    intel_dir.mkdir(parents=True, exist_ok=True)
    (intel_dir / f"{profile}-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
        json.dumps(report, indent=2))
    (intel_dir / "latest.json").write_text(json.dumps(report, indent=2))
    return report
