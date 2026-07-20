import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from main import CloserError, list_overdue, resolve, resolve_commit, resolve_kill, track

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
FAR_FUTURE = (date.today() + timedelta(days=60)).isoformat()


def _nogo(**overrides):
    base = {
        "unlock_condition": "signups exceed 500/week",
        "recheck_date": FAR_FUTURE,
        "redirect_use": "reallocate to reddit_crawler scheduling",
    }
    base.update(overrides)
    return base


def test_track_rejects_bad_deadline():
    with pytest.raises(CloserError, match="ISO date"):
        track("t1", "title", "next tuesday")


def test_list_overdue_flags_open_past_deadline():
    overdue_thread = track("t1", "overdue thing", YESTERDAY)
    fine_thread = track("t2", "fine thing", TOMORROW)
    result = list_overdue([overdue_thread, fine_thread])
    assert [t.item_id for t in result] == ["t1"]


def test_list_overdue_ignores_resolved_threads():
    thread = track("t1", "overdue thing", YESTERDAY)
    resolve_commit(thread, FAR_FUTURE, "2 more weeks of engineer0 time")
    assert list_overdue([thread]) == []


def test_resolve_commit_requires_future_deadline():
    thread = track("t1", "title", YESTERDAY)
    with pytest.raises(CloserError, match="future"):
        resolve_commit(thread, YESTERDAY, "more budget")


def test_resolve_commit_requires_resources():
    thread = track("t1", "title", YESTERDAY)
    with pytest.raises(CloserError, match="new_resources"):
        resolve_commit(thread, FAR_FUTURE, "  ")


def test_resolve_commit_success():
    thread = track("t1", "title", YESTERDAY)
    resolve_commit(thread, FAR_FUTURE, "one more sprint")
    assert thread.status == "committed"
    assert thread.deadline == FAR_FUTURE


def test_resolve_kill_uses_nogo_schema():
    thread = track("t1", "title", YESTERDAY)
    resolve_kill(thread, _nogo())
    assert thread.status == "killed"
    assert thread.resolution["unlock_condition"] == "signups exceed 500/week"


def test_resolve_kill_rejects_invalid_nogo():
    thread = track("t1", "title", YESTERDAY)
    with pytest.raises(Exception):  # NoGoValidationError bubbles up
        resolve_kill(thread, _nogo(unlock_condition="if things improve"))


def test_resolve_kill_decision_id_must_match_thread():
    thread = track("t1", "title", YESTERDAY)
    with pytest.raises(CloserError, match="does not match"):
        resolve_kill(thread, _nogo(decision_id="some-other-id"))


def test_cannot_resolve_twice():
    thread = track("t1", "title", YESTERDAY)
    resolve_commit(thread, FAR_FUTURE, "more time")
    with pytest.raises(CloserError, match="already resolved"):
        resolve_kill(thread, _nogo())


def test_binary_gate_rejects_third_option():
    thread = track("t1", "title", YESTERDAY)
    with pytest.raises(CloserError, match="commit.*kill"):
        resolve(thread, {"type": "defer"})


def test_binary_gate_dispatches_commit():
    thread = track("t1", "title", YESTERDAY)
    resolve(thread, {"type": "commit", "new_deadline": FAR_FUTURE, "new_resources": "budget"})
    assert thread.status == "committed"


def test_binary_gate_dispatches_kill():
    thread = track("t1", "title", YESTERDAY)
    resolve(thread, {"type": "kill", **_nogo()})
    assert thread.status == "killed"
