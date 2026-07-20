"""
Closer — CEO subordinate.

Forces a binary call on every open thread past deadline: commit (new
resources/timeline) or kill (produces a no-go deliverable). No third option
— a thread that's neither doesn't get to stay open silently.

Imports the no-go schema from ../../schemas/nogo_deliverable.py (the single
source of truth for what a valid kill looks like — Watcher consumes the same
schema, so Closer can't invent its own looser version).

Run with: python main.py --threads threads.json [--resolve resolution.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
SCHEMAS_DIR = ROOT.parents[1] / "schemas"
sys.path.insert(0, str(SCHEMAS_DIR))

from nogo_deliverable import NoGoValidationError, validate_nogo_deliverable  # noqa: E402

logger = logging.getLogger("closer")
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


# ── Chronicle logging (see auditor/main.py for the same pattern) ─────────────

def log_event(*, kind: str, action: str, outcome: str = "ok", target: str = "",
              object: str = "", detail: str = "") -> None:
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "actor": "closer",
        "target": target,
        "object": object,
        "action": action,
        "outcome": outcome,
        "detail": detail[:200],
    }
    logger.info(json.dumps(event))
    key = os.environ.get("CHRONICLE_INGEST_KEY", "")
    if not key:
        return
    url = os.environ.get("CHRONICLE_URL", "http://100.67.171.41:5010")
    try:
        httpx.post(f"{url}/api/tools/execute",
                   json={"tool": "chronicle_ingest", "params": {"key": key, "events": [event]}},
                   timeout=3.0)
    except Exception as exc:
        logger.warning(json.dumps({"chronicle_emit_failed": str(exc)}))


# ── Deadline tracker ───────────────────────────────────────────────────────────

class CloserError(ValueError):
    pass


@dataclass
class Thread:
    item_id: str
    title: str
    deadline: str  # ISO date
    status: str = "open"  # open | committed | killed
    resolution: dict[str, Any] | None = None


def track(item_id: str, title: str, deadline: str) -> Thread:
    if not item_id.strip() or not title.strip():
        raise CloserError("item_id and title are required")
    try:
        date.fromisoformat(deadline)
    except ValueError as exc:
        raise CloserError(f"deadline {deadline!r} is not an ISO date (YYYY-MM-DD)") from exc
    return Thread(item_id=item_id, title=title, deadline=deadline)


def list_overdue(threads: list[Thread], now: date | None = None) -> list[Thread]:
    """Escalation: threads still open past their deadline."""
    today = now or datetime.now().date()
    overdue = [t for t in threads if t.status == "open" and date.fromisoformat(t.deadline) < today]
    for t in overdue:
        log_event(kind="closer", action="escalate", outcome="warn", target=t.item_id,
                  detail=f"overdue since {t.deadline}, must resolve to commit or kill")
    return overdue


# ── Binary gate ────────────────────────────────────────────────────────────────

def resolve_commit(thread: Thread, new_deadline: str, new_resources: str) -> Thread:
    if thread.status != "open":
        raise CloserError(f"thread {thread.item_id} already resolved as {thread.status!r}")
    if not new_resources.strip():
        raise CloserError("commit requires new_resources (what's being committed)")
    try:
        parsed = date.fromisoformat(new_deadline)
    except ValueError as exc:
        raise CloserError(f"new_deadline {new_deadline!r} is not an ISO date") from exc
    if parsed <= datetime.now().date():
        raise CloserError(f"new_deadline {new_deadline!r} must be in the future — a commit needs real runway")

    thread.status = "committed"
    thread.deadline = new_deadline
    thread.resolution = {"type": "commit", "new_deadline": new_deadline, "new_resources": new_resources}
    log_event(kind="closer", action="commit", outcome="ok", target=thread.item_id,
              detail=f"new deadline {new_deadline}, resources: {new_resources}")
    return thread


def resolve_kill(thread: Thread, nogo_data: dict[str, Any]) -> Thread:
    if thread.status != "open":
        raise CloserError(f"thread {thread.item_id} already resolved as {thread.status!r}")

    payload = dict(nogo_data)
    payload.setdefault("decision_id", thread.item_id)
    if payload["decision_id"] != thread.item_id:
        raise CloserError(
            f"kill resolution decision_id {payload['decision_id']!r} does not match "
            f"thread {thread.item_id!r}"
        )

    nogo = validate_nogo_deliverable(payload)  # raises NoGoValidationError if invalid

    thread.status = "killed"
    thread.resolution = {"type": "kill", **nogo.to_dict()}
    log_event(kind="closer", action="kill", outcome="ok", target=thread.item_id,
              detail=f"unlock: {nogo.unlock_condition}, recheck: {nogo.recheck_date}")
    return thread


def resolve(thread: Thread, resolution: dict[str, Any]) -> Thread:
    """Dispatch by resolution['type']. Anything besides 'commit'/'kill' is rejected —
    the binary gate has exactly two doors."""
    kind = resolution.get("type")
    if kind == "commit":
        return resolve_commit(thread, resolution["new_deadline"], resolution["new_resources"])
    if kind == "kill":
        nogo_data = {k: v for k, v in resolution.items() if k != "type"}
        return resolve_kill(thread, nogo_data)
    raise CloserError(f"resolution type must be 'commit' or 'kill', got {kind!r}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Closer — CEO subordinate")
    parser.add_argument("--threads", type=Path, required=True, help="Path to threads JSON list")
    parser.add_argument("--resolve", type=Path, default=None,
                         help="Path to {item_id, resolution} JSON to apply")
    args = parser.parse_args()

    raw = json.loads(args.threads.read_text())
    threads = [track(t["item_id"], t["title"], t["deadline"]) for t in raw]

    if args.resolve:
        req = json.loads(args.resolve.read_text())
        target = next((t for t in threads if t.item_id == req["item_id"]), None)
        if target is None:
            raise CloserError(f"no thread with item_id {req['item_id']!r}")
        resolve(target, req["resolution"])
        print(json.dumps(asdict(target), indent=2))
        return

    overdue = list_overdue(threads)
    print(json.dumps([asdict(t) for t in overdue], indent=2))


if __name__ == "__main__":
    main()
