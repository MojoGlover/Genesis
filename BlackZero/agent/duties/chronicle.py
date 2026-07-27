"""
chronicle.py — record duty evidence to the grid's ordering authority.

DECENTRALIZED EXECUTION, CENTRALIZED ORDERING
---------------------------------------------
Every node runs its own timers. Nothing coordinates them, nothing has to agree,
and a node that loses the network keeps doing its job. That is the right design
for recurring work — the alternative is a scheduler whose failure silences the
whole grid.

But independent nodes need a tiebreaker. Two agents can report on the same thing
with clocks that disagree, and "whose report is authoritative" cannot be settled
by comparing wall clocks that were never synchronized.

Chronicle already solves this. Its records carry:

    seq        monotonic, assigned by Chronicle    → total order
    prev_hash  / hash                              → tamper-evident chain
    ts         what the reporting node claims
    recv_ts    when Chronicle actually saw it

`seq` is the tiebreaker. It does not depend on any node's clock being right —
only on Chronicle receiving the events. And keeping both `ts` and `recv_ts`
makes clock drift *measurable* instead of invisible: the gap between them is the
skew, per node, observable after the fact.

FAILURE MODE
------------
Chronicle being unreachable must never stop a duty from running. The recorder is
not allowed to block the work — that would make the audit trail a single point
of failure for the thing it audits. Unsent records spool to disk and flush on a
later run, so a partitioned node keeps working and its history arrives late but
intact, in chain order.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["record_duty", "flush_spool", "node_id"]

_TIMEOUT = 8
_SPOOL_LIMIT = 500  # bounded — a long partition must not fill the disk


def node_id() -> str:
    """Which plug this ran on. Env first so a stamped agent is portable."""
    return os.environ.get("PLUG_NAME") or os.environ.get("PLUG_HOST") or socket.gethostname()


def _spool_path(data_dir: Path) -> Path:
    return Path(data_dir).expanduser() / "chronicle_spool.jsonl"


def _event(report: dict, agent_id: str) -> dict:
    """Shape a duty report as a Chronicle event.

    Deliberately records the OUTCOME and where the evidence lives, not the full
    report — Chronicle is the ordering authority and index, not a second copy of
    every artifact.
    """
    return {
        "kind": "duty",
        "actor": agent_id,
        "action": report.get("duty", "unknown"),
        "object": report.get("tool", ""),
        "outcome": "ok" if report.get("ok") else "failed",
        "duration_ms": int(float(report.get("duration_seconds", 0)) * 1000),
        "detail": {
            "node": node_id(),
            "ran_at": report.get("ran_at"),
            "escalate": report.get("escalate"),
            "new_items": report.get("new"),
            "record": report.get("record"),
        },
    }


def _post(url: str, payload: dict) -> bool:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        logger.debug("[chronicle] unreachable: %s", e)
        return False


def _spool(data_dir: Path, event: dict) -> None:
    path = _spool_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text().splitlines() if path.exists() else []
    except OSError:
        lines = []
    lines.append(json.dumps(event))
    path.write_text("\n".join(lines[-_SPOOL_LIMIT:]) + "\n")


def flush_spool(data_dir: Path, chronicle_url: str) -> int:
    """Send anything queued during an outage. Order is preserved — the chain
    should reflect the sequence work actually happened in, not the order a
    recovering node happened to retry."""
    path = _spool_path(data_dir)
    if not path.exists():
        return 0
    try:
        pending = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except (OSError, json.JSONDecodeError):
        return 0

    sent = 0
    for i, ev in enumerate(pending):
        if not _post(f"{chronicle_url.rstrip('/')}/api/tools/execute",
                     {"tool": "chronicle_ingest", "params": ev}):
            # Stop at the first failure and keep the rest in order.
            remaining = pending[i:]
            path.write_text("\n".join(json.dumps(e) for e in remaining) + "\n")
            return sent
        sent += 1

    path.unlink(missing_ok=True)
    return sent


def record_duty(report: dict, agent_id: str, data_dir: Path,
                chronicle_url: str | None) -> dict:
    """Record a duty outcome. Never raises, never blocks the duty.

    Returns a small status dict so the caller can see whether the grid's
    ordering authority actually has this event, rather than assuming it does.
    """
    if not chronicle_url:
        return {"recorded": False, "reason": "no chronicle_url configured"}

    event = _event(report, agent_id)
    event["client_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    flushed = flush_spool(data_dir, chronicle_url)

    if _post(f"{chronicle_url.rstrip('/')}/api/tools/execute",
             {"tool": "chronicle_ingest", "params": event}):
        return {"recorded": True, "flushed": flushed, "node": node_id()}

    _spool(data_dir, event)
    return {"recorded": False, "spooled": True, "flushed": flushed,
            "reason": "chronicle unreachable — queued, work continued"}
