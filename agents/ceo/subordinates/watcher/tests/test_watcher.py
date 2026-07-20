import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "schemas"))

import pytest

from main import (
    LedgerEntry,
    NoGoLedger,
    _flatten_ledger_budget,
    evaluate_entry,
    fetch_accountant_snapshot,
    monitor,
    parse_condition,
)
from nogo_deliverable import validate_nogo_deliverable

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def _nogo(**overrides):
    # recheck_date must not be in the past at schema-validation time (a no-go
    # is created with a forward-looking recheck), so use TODAY here — evaluate_entry
    # treats "today == recheck_date" as due, same as any date in the past would be.
    base = {
        "decision_id": "dec-1",
        "unlock_condition": "MRR exceeds $10,000",
        "recheck_date": TODAY,
        "redirect_use": "reallocate to youtube_crawler",
    }
    base.update(overrides)
    return validate_nogo_deliverable(base)


@pytest.fixture
def ledger(tmp_path):
    return NoGoLedger(tmp_path / "ledger.jsonl")


def test_parse_condition_extracts_metric_comparator_threshold():
    assert parse_condition("MRR exceeds $10,000") == ("mrr", ">", 10000.0)
    assert parse_condition("signups > 500") == ("signups", ">", 500.0)
    assert parse_condition("churn falls below 3") == ("churn", "<", 3.0)


def test_parse_condition_unparseable_returns_none():
    assert parse_condition("waits 6 months from kill date") is None


# recheck_date not yet reached -> dormant even if the metric already qualifies
def test_dormant_before_recheck_date():
    entry = LedgerEntry(decision_id="d1", unlock_condition="MRR exceeds $10,000",
                         recheck_date=TOMORROW, redirect_use="x")
    status = evaluate_entry(entry, {"mrr": 50000}, now=date.today())
    assert status == "dormant"


# condition not met -> stays dormant/watching, not triggered
def test_condition_not_met_stays_watching():
    entry = LedgerEntry(decision_id="d1", unlock_condition="MRR exceeds $10,000",
                         recheck_date=YESTERDAY, redirect_use="x")
    status = evaluate_entry(entry, {"mrr": 4000}, now=date.today())
    assert status == "watching"


# condition met -> surfaces
def test_condition_met_triggers():
    entry = LedgerEntry(decision_id="d1", unlock_condition="MRR exceeds $10,000",
                         recheck_date=YESTERDAY, redirect_use="x")
    status = evaluate_entry(entry, {"mrr": 15000}, now=date.today())
    assert status == "triggered"


# missing Accountant data source -> degraded, not a false trigger
def test_missing_data_source_degrades_not_crashes():
    entry = LedgerEntry(decision_id="d1", unlock_condition="MRR exceeds $10,000",
                         recheck_date=YESTERDAY, redirect_use="x")
    status = evaluate_entry(entry, None, now=date.today())
    assert status == "degraded"


def test_metric_absent_from_snapshot_degrades():
    entry = LedgerEntry(decision_id="d1", unlock_condition="MRR exceeds $10,000",
                         recheck_date=YESTERDAY, redirect_use="x")
    status = evaluate_entry(entry, {"signups": 900}, now=date.today())
    assert status == "degraded"


def test_unparseable_condition_degrades_after_recheck_date():
    entry = LedgerEntry(decision_id="d1", unlock_condition="waits 6 months from kill date",
                         recheck_date=YESTERDAY, redirect_use="x")
    status = evaluate_entry(entry, {"mrr": 999999}, now=date.today())
    assert status == "degraded"


def test_ledger_add_and_load_roundtrip(ledger):
    nogo = _nogo()
    ledger.add(nogo)
    entries = ledger.load()
    assert len(entries) == 1
    assert entries[0].decision_id == "dec-1"
    assert entries[0].status == "dormant"


def test_ledger_rejects_duplicate_decision_id(ledger):
    ledger.add(_nogo())
    with pytest.raises(ValueError, match="already on the ledger"):
        ledger.add(_nogo())


def test_monitor_surfaces_triggered_entry(ledger):
    ledger.add(_nogo())
    surfaced = monitor(ledger, {"mrr": 20000}, now=date.today())
    assert len(surfaced) == 1
    assert surfaced[0].decision_id == "dec-1"
    assert surfaced[0].status == "triggered"
    assert surfaced[0].surfaced_at is not None


def test_monitor_never_resurfaces_same_entry_twice(ledger):
    ledger.add(_nogo())
    first = monitor(ledger, {"mrr": 20000}, now=date.today())
    second = monitor(ledger, {"mrr": 20000}, now=date.today())
    assert len(first) == 1
    assert len(second) == 0  # idempotent — already surfaced


def test_monitor_never_auto_reverses_ledger_status(ledger):
    ledger.add(_nogo())
    monitor(ledger, {"mrr": 20000}, now=date.today())
    entries = ledger.load()
    # status is "triggered" (surfaced), never anything implying reopened/resolved
    assert entries[0].status == "triggered"
    assert entries[0].status not in ("reopened", "resolved", "committed")


def test_monitor_does_not_trigger_without_data(ledger):
    ledger.add(_nogo())
    surfaced = monitor(ledger, None, now=date.today())
    assert surfaced == []
    entries = ledger.load()
    assert entries[0].status == "degraded"


# ── Live Accountant integration ──────────────────────────────────────────────
# Accountant is a real agent (Botico/agents/accountant, port 5002 locally) —
# these test the parsing logic against her real ledger_budget response shape,
# and the fetch path's graceful-degrade behavior, without depending on a
# live server being up during test runs.

def test_flatten_ledger_budget_matches_real_response_shape():
    # Shape from accountant/agent/tools/financial.py::ledger_budget
    budget = {"ok": True, "cap_usd": 50.0, "window_days": 30,
              "spend_in_window_usd": 12.5, "remaining_usd": 37.5, "pct_used": 25.0}
    flat = _flatten_ledger_budget("engineer0", budget)
    assert flat == {
        "engineer0_spend_usd": 12.5,
        "engineer0_pct_used": 25.0,
        "engineer0_remaining_usd": 37.5,
        "engineer0_cap_usd": 50.0,
    }


def test_fetch_accountant_snapshot_no_agents_returns_none():
    assert fetch_accountant_snapshot("http://localhost:5002", []) is None


def test_fetch_accountant_snapshot_unreachable_degrades_to_none():
    # Port 1 is a reserved/refused port on localhost — fails fast, no live
    # server dependency, exercises the same path as Accountant actually being down.
    result = fetch_accountant_snapshot("http://localhost:1", ["engineer0"], timeout=1.0)
    assert result is None


def test_evaluate_entry_uses_flattened_accountant_metric_keys():
    entry = LedgerEntry(decision_id="d1", unlock_condition="engineer0_spend_usd exceeds 100",
                         recheck_date=TODAY, redirect_use="x")
    snapshot = _flatten_ledger_budget("engineer0", {"spend_in_window_usd": 150.0})
    status = evaluate_entry(entry, snapshot, now=date.today())
    assert status == "triggered"
