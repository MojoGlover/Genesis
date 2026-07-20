import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from main import (
    ArtifactResolver,
    ClaimIntakeError,
    StatusLockError,
    audit_claim,
    close_task,
    intake_claim,
    match_check,
)


@pytest.fixture
def resolver(tmp_path):
    return ArtifactResolver(str(tmp_path))


def _claim(**overrides):
    base = {
        "claim_id": "claim-1",
        "agent_id": "engineer0",
        "task_id": "task-42",
        "claim_text": "rebuilt accountant service",
        "artifact_path": "artifact.log",
    }
    base.update(overrides)
    return base


# (a) done claim with no artifact -> rejected
def test_done_claim_no_artifact_rejected(resolver):
    verdict = audit_claim(_claim(artifact_path="missing.log"), resolver)
    assert verdict.status == "rejected"
    assert "no artifact found" in verdict.reason


# (b) done claim with mismatched artifact -> flagged
def test_done_claim_mismatched_artifact_flagged(resolver, tmp_path):
    (tmp_path / "artifact.log").write_text("Traceback (most recent call last):\nAssertionError: boom")
    verdict = audit_claim(_claim(), resolver)
    assert verdict.status == "flagged"


# (c) done claim with matching artifact -> approved
def test_done_claim_matching_artifact_approved(resolver, tmp_path):
    (tmp_path / "artifact.log").write_text("5 passed in 0.02s")
    verdict = audit_claim(_claim(), resolver)
    assert verdict.status == "approved"


def test_expected_pattern_match_approved(resolver, tmp_path):
    (tmp_path / "artifact.log").write_text("wrote 12 rows to accountant.sqlite")
    verdict = audit_claim(_claim(expected_pattern=r"wrote \d+ rows"), resolver)
    assert verdict.status == "approved"


def test_expected_pattern_mismatch_flagged(resolver, tmp_path):
    (tmp_path / "artifact.log").write_text("wrote nothing")
    verdict = audit_claim(_claim(expected_pattern=r"wrote \d+ rows"), resolver)
    assert verdict.status == "flagged"


def test_ambiguous_artifact_flagged(resolver, tmp_path):
    (tmp_path / "artifact.log").write_text("service restarted, no summary emitted")
    verdict = audit_claim(_claim(), resolver)
    assert verdict.status == "flagged"
    assert "ambiguous" in verdict.reason


def test_path_escape_treated_as_unresolved(resolver, tmp_path):
    outside = tmp_path.parent / "secret.log"
    outside.write_text("passed")
    verdict = audit_claim(_claim(artifact_path="../secret.log"), resolver)
    assert verdict.status == "rejected"


def test_intake_missing_field_raises():
    with pytest.raises(ClaimIntakeError, match="claim_text"):
        intake_claim({"claim_id": "c1", "agent_id": "a", "task_id": "t", "artifact_path": "x"})


def test_close_task_blocks_without_approval(resolver, tmp_path):
    (tmp_path / "artifact.log").write_text("FAILED test_foo")
    claim = intake_claim(_claim())
    verdict = match_check(claim, resolver)
    with pytest.raises(StatusLockError):
        close_task(claim, verdict)


def test_close_task_succeeds_with_approval(resolver, tmp_path):
    (tmp_path / "artifact.log").write_text("all tests passed")
    claim = intake_claim(_claim())
    verdict = match_check(claim, resolver)
    close_task(claim, verdict)  # should not raise
