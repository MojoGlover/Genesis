"""
Watcher — CEO subordinate.

Monitors killed decisions so they don't silently become permanent. Never
auto-reverses a kill — it only surfaces a resurrection candidate to the CEO
for a human/Adversary/Closer decision. Reads the no-go schema from
../../schemas/nogo_deliverable.py, same source of truth Closer writes
against.

Accountant ("Danika Franklin") is a live agent at Botico/agents/accountant,
reachable over the grid's standard Tool Bus HTTP pattern
(POST {ACCOUNTANT_URL}/api/tools/execute, X-Agent-Id header, tool
"ledger_budget" — see agent/api/server.py + agent/tools/financial.py in her
repo). fetch_accountant_snapshot() calls that live endpoint per watched
agent_id (ACCOUNTANT_WATCHED_AGENTS) and flattens the response into
{agent_id}_spend_usd / {agent_id}_pct_used / {agent_id}_remaining_usd
metrics. Her actual ledger_budget backend is model_gateway (port 9109) —
if that's down (it returned "model_gateway unreachable" when this was
verified 2026-07-20) or Accountant herself isn't reachable, the fetch
degrades loudly rather than guessing: same never-false-trigger contract as
before, now against the real dependency instead of a placeholder.
ACCOUNTANT_LEDGER_PATH still exists as a manual JSON-snapshot override for
offline testing.

Run with: python main.py --ledger ledger.jsonl [--data accountant_snapshot.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
SCHEMAS_DIR = ROOT.parents[1] / "schemas"
sys.path.insert(0, str(SCHEMAS_DIR))

from nogo_deliverable import NoGoDeliverable, validate_nogo_deliverable  # noqa: E402

logger = logging.getLogger("watcher")
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


# ── Chronicle logging (see auditor/main.py for the same pattern) ─────────────

def log_event(*, kind: str, action: str, outcome: str = "ok", target: str = "",
              object: str = "", detail: str = "") -> None:
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "actor": "watcher",
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


# ── No-go ledger ────────────────────────────────────────────────────────────────

STATUSES = ("dormant", "watching", "degraded", "triggered")


@dataclass
class LedgerEntry:
    decision_id: str
    unlock_condition: str
    recheck_date: str
    redirect_use: str
    reason: str = ""
    status: str = "dormant"
    surfaced_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LedgerEntry":
        return cls(**d)


class NoGoLedger:
    """Stores killed decisions as JSON Lines. Append-only intake, in-place status updates."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    def add(self, nogo: NoGoDeliverable) -> LedgerEntry:
        entry = LedgerEntry(decision_id=nogo.decision_id, unlock_condition=nogo.unlock_condition,
                             recheck_date=nogo.recheck_date, redirect_use=nogo.redirect_use,
                             reason=nogo.reason)
        entries = self.load()
        if any(e.decision_id == entry.decision_id for e in entries):
            raise ValueError(f"decision_id {entry.decision_id!r} already on the ledger")
        entries.append(entry)
        self._save(entries)
        log_event(kind="watcher", action="ledger_add", outcome="ok", target=entry.decision_id,
                  detail=f"unlock: {entry.unlock_condition}, recheck: {entry.recheck_date}")
        return entry

    def load(self) -> list[LedgerEntry]:
        lines = [l for l in self.path.read_text().splitlines() if l.strip()]
        return [LedgerEntry.from_dict(json.loads(l)) for l in lines]

    def _save(self, entries: list[LedgerEntry]) -> None:
        self.path.write_text("\n".join(json.dumps(e.to_dict()) for e in entries) + ("\n" if entries else ""))

    def update(self, entries: list[LedgerEntry]) -> None:
        self._save(entries)


# ── Condition monitor ─────────────────────────────────────────────────────────

_COMPARATOR_WORDS = {
    "exceeds": ">", "above": ">", "greater than": ">",
    "falls below": "<", "below": "<", "under": "<",
    "at least": ">=", "hits": "==", "equals": "==", "reaches": ">=",
}
_CONDITION_RE = re.compile(
    r"(?P<metric>[A-Za-z][A-Za-z0-9_ ]*?)\s*"
    r"(?P<comparator>>=|<=|==|>|<|exceeds|above|greater than|falls below|below|under|at least|hits|equals|reaches)\s*"
    r"\$?(?P<threshold>[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_condition(unlock_condition: str) -> tuple[str, str, float] | None:
    match = _CONDITION_RE.search(unlock_condition)
    if not match:
        return None
    metric = match.group("metric").strip().lower()
    comparator_raw = match.group("comparator").strip().lower()
    comparator = _COMPARATOR_WORDS.get(comparator_raw, comparator_raw)
    threshold = float(match.group("threshold").replace(",", ""))
    return metric, comparator, threshold


def _compare(value: float, comparator: str, threshold: float) -> bool:
    return {
        ">": value > threshold, "<": value < threshold,
        ">=": value >= threshold, "<=": value <= threshold,
        "==": value == threshold,
    }[comparator]


def evaluate_entry(entry: LedgerEntry, data_source: dict[str, float] | None,
                    now: date | None = None) -> str:
    """Returns the entry's new status. Never mutates entry — caller applies it."""
    today = now or datetime.now().date()
    if today < date.fromisoformat(entry.recheck_date):
        return "dormant"

    parsed = parse_condition(entry.unlock_condition)
    if parsed is None:
        return "degraded"  # not mechanically parseable — needs a human read, not a false trigger

    metric, comparator, threshold = parsed
    if data_source is None:
        return "degraded"  # Accountant ledger unavailable — degrade loudly, don't guess

    matched_key = next((k for k in data_source if metric in k.lower() or k.lower() in metric), None)
    if matched_key is None:
        return "degraded"  # recheck_date passed but the metric isn't in the snapshot we got

    return "triggered" if _compare(data_source[matched_key], comparator, threshold) else "watching"


def _flatten_ledger_budget(agent_id: str, budget: dict[str, Any]) -> dict[str, float]:
    """Pure — turns one ledger_budget response into flat metric keys.
    budget shape (financial.ledger_budget): cap_usd, spend_in_window_usd,
    remaining_usd, pct_used, window_days."""
    out: dict[str, float] = {}
    for field, suffix in (("spend_in_window_usd", "spend_usd"),
                           ("pct_used", "pct_used"),
                           ("remaining_usd", "remaining_usd"),
                           ("cap_usd", "cap_usd")):
        if field in budget:
            out[f"{agent_id}_{suffix}"] = float(budget[field])
    return out


def fetch_accountant_snapshot(
    accountant_url: str, agent_ids: list[str], requester_id: str = "ceo-watcher",
    timeout: float = 5.0,
) -> dict[str, float] | None:
    """Live call to Accountant's Tool Bus endpoint (same pattern every grid
    agent uses to borrow another agent's tools — see accountant/agent/api/server.py).
    Returns None only if EVERY agent_id fails (Accountant unreachable, or her
    model_gateway backend is down) — partial results from some agent_ids still
    count as real data for those metrics."""
    if not agent_ids:
        return None
    snapshot: dict[str, float] = {}
    any_ok = False
    with httpx.Client(timeout=timeout) as client:
        for agent_id in agent_ids:
            try:
                resp = client.post(
                    f"{accountant_url.rstrip('/')}/api/tools/execute",
                    json={"tool": "ledger_budget", "params": {"agent_id": agent_id}},
                    headers={"X-Agent-Id": requester_id},
                )
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok"):
                    log_event(kind="watcher", action="accountant_fetch", outcome="warn",
                              target=agent_id, detail=str(body.get("result"))[:150])
                    continue
                budget = json.loads(body["result"])  # ledger_budget returns raw JSON in "result"
                snapshot.update(_flatten_ledger_budget(agent_id, budget))
                any_ok = True
            except Exception as exc:
                log_event(kind="watcher", action="accountant_fetch", outcome="error",
                          target=agent_id, detail=str(exc)[:150])
    return snapshot if any_ok else None


def _load_accountant_data(path: str | None) -> dict[str, float] | None:
    """Manual JSON-snapshot override — for offline testing or a stand-in when
    Accountant/model_gateway genuinely can't be reached. fetch_accountant_snapshot()
    is the real path; this is the fallback, not the primary source.
    Returns None (not {}) when unavailable so callers can tell 'no data' from 'empty data'."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


# ── Trigger / surface ──────────────────────────────────────────────────────────

def monitor(ledger: NoGoLedger, data_source: dict[str, float] | None,
            now: date | None = None) -> list[LedgerEntry]:
    """Evaluates every dormant/watching/degraded entry. Returns entries newly
    surfaced this pass (status just became 'triggered' and hadn't been surfaced
    before). Idempotent — an already-surfaced entry isn't re-surfaced."""
    entries = ledger.load()
    newly_surfaced: list[LedgerEntry] = []

    for entry in entries:
        new_status = evaluate_entry(entry, data_source, now)
        if new_status == "triggered" and entry.surfaced_at is None:
            entry.status = "triggered"
            entry.surfaced_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            newly_surfaced.append(entry)
            log_event(kind="watcher", action="surface_resurrection", outcome="ok",
                      target=entry.decision_id,
                      detail=f"unlock condition met: {entry.unlock_condition} — surfaced to CEO, not auto-reopened")
        elif new_status == "degraded" and entry.status != "triggered":
            entry.status = "degraded"
            log_event(kind="watcher", action="condition_check", outcome="warn",
                      target=entry.decision_id, detail="condition monitoring degraded — no reliable data source")
        elif entry.status != "triggered":
            entry.status = new_status

    ledger.update(entries)
    return newly_surfaced


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Watcher — CEO subordinate")
    parser.add_argument("--ledger", type=Path, default=ROOT / "ledger.jsonl")
    parser.add_argument("--data", type=str, default=os.environ.get("ACCOUNTANT_LEDGER_PATH"),
                         help="Manual JSON metric snapshot override (skips the live Accountant call)")
    parser.add_argument("--add", type=Path, default=None, help="Path to a no-go JSON to add to the ledger")
    args = parser.parse_args()

    ledger = NoGoLedger(args.ledger)

    if args.add:
        nogo = validate_nogo_deliverable(json.loads(args.add.read_text()))
        entry = ledger.add(nogo)
        print(json.dumps(entry.to_dict(), indent=2))
        return

    if args.data:
        data_source = _load_accountant_data(args.data)
    else:
        accountant_url = os.environ.get("ACCOUNTANT_URL", "http://localhost:5002")
        watched_agents = [a.strip() for a in
                           os.environ.get("ACCOUNTANT_WATCHED_AGENTS", "").split(",") if a.strip()]
        data_source = fetch_accountant_snapshot(accountant_url, watched_agents)

    surfaced = monitor(ledger, data_source)
    print(json.dumps([e.to_dict() for e in surfaced], indent=2))


if __name__ == "__main__":
    main()
