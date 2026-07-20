from datetime import date, timedelta

import pytest

from nogo_deliverable import NoGoValidationError, validate_nogo_deliverable

FUTURE = (date.today() + timedelta(days=30)).isoformat()
PAST = (date.today() - timedelta(days=1)).isoformat()


def _valid(**overrides):
    base = {
        "decision_id": "dec-2026-07-20-001",
        "unlock_condition": "MRR exceeds $10,000 for 2 consecutive months",
        "recheck_date": FUTURE,
        "redirect_use": "reallocate to Karma KaMillion crawler build-out",
    }
    base.update(overrides)
    return base


def test_valid_intake_passes():
    result = validate_nogo_deliverable(_valid())
    assert result.decision_id == "dec-2026-07-20-001"
    assert result.recheck_date == FUTURE


@pytest.mark.parametrize("missing_field", ["decision_id", "unlock_condition", "recheck_date", "redirect_use"])
def test_missing_required_field_rejected(missing_field):
    data = _valid()
    del data[missing_field]
    with pytest.raises(NoGoValidationError, match=missing_field):
        validate_nogo_deliverable(data)


def test_blank_required_field_rejected():
    data = _valid(redirect_use="   ")
    with pytest.raises(NoGoValidationError, match="redirect_use"):
        validate_nogo_deliverable(data)


def test_non_dict_rejected():
    with pytest.raises(NoGoValidationError):
        validate_nogo_deliverable("not a dict")  # type: ignore[arg-type]


def test_malformed_date_rejected():
    with pytest.raises(NoGoValidationError, match="ISO date"):
        validate_nogo_deliverable(_valid(recheck_date="next quarter"))


def test_past_date_rejected():
    with pytest.raises(NoGoValidationError, match="past"):
        validate_nogo_deliverable(_valid(recheck_date=PAST))


@pytest.mark.parametrize("vague", [
    "if things improve",
    "when appropriate",
    "revisit later",
    "TBD",
    "we'll see how it goes",
])
def test_vague_unlock_condition_rejected(vague):
    with pytest.raises(NoGoValidationError, match="vague"):
        validate_nogo_deliverable(_valid(unlock_condition=vague))


def test_unchecakble_prose_without_threshold_rejected():
    with pytest.raises(NoGoValidationError, match="checkable threshold"):
        validate_nogo_deliverable(_valid(unlock_condition="the market feels healthier"))


@pytest.mark.parametrize("condition", [
    "MRR exceeds $10,000 for 2 consecutive months",
    "signups > 500/week",
    "churn falls below 3%",
    "waits 6 months from kill date",
])
def test_checkable_unlock_conditions_accepted(condition):
    result = validate_nogo_deliverable(_valid(unlock_condition=condition))
    assert result.unlock_condition == condition


def test_to_dict_roundtrip():
    result = validate_nogo_deliverable(_valid())
    d = result.to_dict()
    assert d["decision_id"] == result.decision_id
    assert set(d.keys()) == {"decision_id", "unlock_condition", "recheck_date", "redirect_use", "reason"}
