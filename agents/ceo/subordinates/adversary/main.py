"""
Adversary — CEO subordinate.

Forces the CEO to argue against his own decision before it becomes final.
No LLM (grid policy: no cloud inference without an Accountant spend gate,
which doesn't exist yet — see cmptrblk/CLAUDE.md Cloud API Policy). Instead
this runs a deterministic checklist of standard decision failure modes
against the CEO's own reasoning text: whichever category the reasoning
defends *least* is rendered into a concrete, decision-specific counter-case.
That's the "strongest case against" — not the most dramatic-sounding
objection, but the gap the CEO is currently least prepared to answer.

Decision states: draft -> contested -> final. A decision cannot reach
`final` without a logged rebuttal that references specific counter-case ids
by id (a rebuttal that ignores the counter-cases doesn't count).

Run with: python main.py --decision decision.json [--rebuttal rebuttal.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger("adversary")
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


# ── Chronicle logging (see auditor/main.py for the same pattern) ─────────────

def log_event(*, kind: str, action: str, outcome: str = "ok", target: str = "",
              object: str = "", detail: str = "") -> None:
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "actor": "adversary",
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


# ── Failure-mode checklist ────────────────────────────────────────────────────
# Priority order is the tie-break when two categories are equally undefended
# (fewest keyword hits) — reversibility and resource contention bite hardest
# in practice, so they lead.

CHECKLIST: dict[str, dict[str, Any]] = {
    "reversibility": {
        "keywords": ("revers", "undo", "rollback", "exit plan", "fallback"),
        "template": "If {proposal} turns out wrong, what's the rollback? "
                    "The reasoning never addresses whether this is reversible.",
    },
    "resource_contention": {
        "keywords": ("resource", "bandwidth", "capacity", "staff", "budget"),
        "template": "Who or what does {proposal} pull resources from? "
                    "The reasoning doesn't account for what it displaces.",
    },
    "unvalidated_assumption": {
        "keywords": ("assum", "validated", "evidence", "data shows", "tested"),
        "template": "What evidence supports {proposal}, versus assumption? "
                    "None is cited in the reasoning.",
    },
    "opportunity_cost": {
        "keywords": ("opportunity cost", "alternative", "instead", "trade-off", "tradeoff"),
        "template": "What does saying yes to {proposal} cost elsewhere? "
                    "The reasoning names no alternative that was considered and rejected.",
    },
    "timing_urgency": {
        "keywords": ("urgent", "deadline", "timing", "why now"),
        "template": "Why does {proposal} have to happen now rather than later? "
                    "The reasoning doesn't establish urgency.",
    },
}
_PRIORITY = list(CHECKLIST.keys())


@dataclass(frozen=True)
class CounterPoint:
    id: str
    text: str
    hits: int  # how many keywords the reasoning already covers for this category (lower = weaker)


def generate_counter_case(decision: dict[str, Any]) -> list[CounterPoint]:
    proposal = decision["proposal"]
    reasoning_lower = decision.get("reasoning", "").lower()

    scored = []
    for category, spec in CHECKLIST.items():
        hits = sum(1 for kw in spec["keywords"] if kw in reasoning_lower)
        text = spec["template"].format(proposal=proposal)
        scored.append(CounterPoint(id=category, text=text, hits=hits))

    scored.sort(key=lambda cp: (cp.hits, _PRIORITY.index(cp.id)))
    return scored


# ── Decision object + state machine ───────────────────────────────────────────

class AdversaryStateError(ValueError):
    pass


class RebuttalError(ValueError):
    pass


REQUIRED_DECISION_FIELDS = ("decision_id", "proposal", "reasoning")


@dataclass
class Decision:
    decision_id: str
    proposal: str
    reasoning: str
    state: str = "draft"
    counter_cases: list[CounterPoint] = field(default_factory=list)
    rebuttal: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def intake_decision(data: dict[str, Any]) -> Decision:
    missing = [f for f in REQUIRED_DECISION_FIELDS if not str(data.get(f, "")).strip()]
    if missing:
        raise ValueError(f"decision intake missing required field(s): {', '.join(missing)}")
    return Decision(decision_id=data["decision_id"], proposal=data["proposal"],
                     reasoning=data["reasoning"])


def contest(decision: Decision) -> Decision:
    """draft -> contested. Generates the counter-case; CEO must answer it to finalize."""
    if decision.state != "draft":
        raise AdversaryStateError(f"cannot contest a decision in state {decision.state!r} (must be 'draft')")
    decision.counter_cases = generate_counter_case(decision.to_dict())
    decision.state = "contested"
    log_event(kind="adversary", action="contest", outcome="ok", target=decision.decision_id,
              detail=f"strongest case: {decision.counter_cases[0].id}")
    return decision


def rebut(decision: Decision, rebuttal_text: str, referenced_ids: list[str]) -> Decision:
    """Records a rebuttal. Does not itself finalize — see finalize()."""
    if decision.state != "contested":
        raise AdversaryStateError(f"cannot rebut a decision in state {decision.state!r} (must be 'contested')")
    if not rebuttal_text.strip():
        raise RebuttalError("rebuttal text is empty")
    valid_ids = {cp.id for cp in decision.counter_cases}
    referenced = set(referenced_ids)
    if not referenced:
        raise RebuttalError("rebuttal references no counter-case ids")
    unknown = referenced - valid_ids
    if unknown:
        raise RebuttalError(f"rebuttal references unknown counter-case id(s): {sorted(unknown)}")
    decision.rebuttal = {"text": rebuttal_text, "references": sorted(referenced)}
    log_event(kind="adversary", action="rebut", outcome="ok", target=decision.decision_id,
              detail=f"references {sorted(referenced)}")
    return decision


def finalize(decision: Decision) -> Decision:
    """contested -> final. Requires a rebuttal that references the strongest case."""
    if decision.state != "contested":
        raise AdversaryStateError(f"cannot finalize a decision in state {decision.state!r} (must be 'contested')")
    if decision.rebuttal is None:
        raise RebuttalError("cannot finalize: no rebuttal logged")
    strongest_id = decision.counter_cases[0].id
    if strongest_id not in decision.rebuttal["references"]:
        raise RebuttalError(
            f"cannot finalize: rebuttal must reference the strongest case ({strongest_id!r}), "
            f"only referenced {decision.rebuttal['references']}"
        )
    decision.state = "final"
    log_event(kind="adversary", action="finalize", outcome="ok", target=decision.decision_id)
    return decision


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Adversary — CEO subordinate")
    parser.add_argument("--decision", type=str, required=True, help="Path to decision JSON")
    parser.add_argument("--rebuttal", type=str, default=None, help="Path to rebuttal JSON")
    args = parser.parse_args()

    with open(args.decision) as f:
        decision = intake_decision(json.load(f))
    decision = contest(decision)

    if args.rebuttal:
        with open(args.rebuttal) as f:
            rebuttal_data = json.load(f)
        decision = rebut(decision, rebuttal_data["text"], rebuttal_data["references"])
        decision = finalize(decision)

    print(json.dumps(decision.to_dict(), indent=2))


if __name__ == "__main__":
    main()
