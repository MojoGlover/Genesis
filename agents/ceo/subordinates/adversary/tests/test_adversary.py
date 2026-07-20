import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from main import (
    AdversaryStateError,
    RebuttalError,
    contest,
    finalize,
    generate_counter_case,
    intake_decision,
    rebut,
)


def _decision(**overrides):
    base = {
        "decision_id": "dec-1",
        "proposal": "spin up a 5th platform crawler",
        "reasoning": "we have bandwidth this sprint and it's a natural extension",
    }
    base.update(overrides)
    return intake_decision(base)


def test_intake_requires_fields():
    with pytest.raises(ValueError, match="reasoning"):
        intake_decision({"decision_id": "d", "proposal": "p", "reasoning": ""})


def test_counter_case_is_decision_specific():
    decision = _decision()
    cases = generate_counter_case(decision.to_dict())
    assert len(cases) == 5
    assert all(decision.proposal in cp.text for cp in cases)


def test_counter_case_ranks_least_defended_first():
    # reasoning defends resource_contention explicitly but nothing else
    decision = _decision(reasoning="we have plenty of staff bandwidth for this")
    cases = generate_counter_case(decision.to_dict())
    assert cases[0].id != "resource_contention"
    assert cases[-1].id == "resource_contention"


def test_cannot_finalize_a_draft():
    decision = _decision()
    with pytest.raises(AdversaryStateError):
        finalize(decision)


def test_cannot_contest_twice():
    decision = contest(_decision())
    with pytest.raises(AdversaryStateError):
        contest(decision)


def test_finalize_without_rebuttal_blocked():
    decision = contest(_decision())
    with pytest.raises(RebuttalError, match="no rebuttal"):
        finalize(decision)


def test_rebuttal_must_reference_known_ids():
    decision = contest(_decision())
    with pytest.raises(RebuttalError, match="unknown"):
        rebut(decision, "we've thought about this", ["not_a_real_category"])


def test_rebuttal_cannot_be_empty_references():
    decision = contest(_decision())
    with pytest.raises(RebuttalError, match="no counter-case"):
        rebut(decision, "trust me", [])


def test_finalize_requires_rebuttal_to_reference_strongest_case():
    decision = contest(_decision())
    strongest_id = decision.counter_cases[0].id
    weakest_addressed_id = decision.counter_cases[-1].id
    # Rebut referencing a weaker case, not the strongest — must not finalize.
    decision = rebut(decision, "we did think about this a little", [weakest_addressed_id])
    if weakest_addressed_id != strongest_id:
        with pytest.raises(RebuttalError, match="strongest case"):
            finalize(decision)


def test_full_flow_reaches_final():
    decision = contest(_decision())
    strongest_id = decision.counter_cases[0].id
    decision = rebut(decision, f"addressing {strongest_id} directly: rollback plan is X",
                      [strongest_id])
    decision = finalize(decision)
    assert decision.state == "final"


def test_generic_rebuttal_text_still_requires_real_reference():
    # A rebuttal can't just reference an id without engaging — but the gate we
    # enforce mechanically is reference-presence; substance is CEO's problem.
    # This test documents that boundary rather than asserting false rigor.
    decision = contest(_decision())
    strongest_id = decision.counter_cases[0].id
    decision = rebut(decision, "noted.", [strongest_id])
    decision = finalize(decision)
    assert decision.rebuttal["references"] == [strongest_id]
