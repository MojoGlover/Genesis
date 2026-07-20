"""
No-Go Deliverable schema — CEO-internal.

The artifact a Closer produces when a decision resolves to "kill" instead of
"commit" (see subordinates/closer). A kill is only valid if it is checkable
later: a vague "revisit if things change" is not a no-go deliverable, it's a
decision quietly rotting. Watcher polls these against real data to decide
whether a killed decision should resurface — never auto-reverses it.

Run standalone tests with: python -m pytest test_nogo_deliverable.py
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

REQUIRED_FIELDS = ("decision_id", "unlock_condition", "recheck_date", "redirect_use")

# unlock_condition must name a metric/threshold/event, not just prose. This is a
# blunt heuristic (not real NLU) but it blocks the most common failure: someone
# writing "if things improve" instead of "if MRR > $10k for 2 consecutive months".
_VAGUE_PHRASES = (
    "if things", "if it feels", "when appropriate", "at some point",
    "revisit later", "tbd", "we'll see", "when ready", "eventually",
)
_CHECKABLE_HINTS = re.compile(
    r"(?:[<>]=?|==|>=|<=|\breaches\b|\bexceeds\b|\bfalls below\b|\bhits\b|"
    r"\d|\$|%|\bfor\b.*\b(day|week|month|quarter)s?\b)",
    re.IGNORECASE,
)


class NoGoValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NoGoDeliverable:
    decision_id: str
    unlock_condition: str
    recheck_date: str  # ISO date, YYYY-MM-DD
    redirect_use: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_str(data: dict[str, Any], field: str, missing: list[str]) -> str:
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        missing.append(field)
        return ""
    if not isinstance(value, str):
        raise NoGoValidationError(f"{field} must be a string, got {type(value).__name__}")
    return value.strip()


def validate_nogo_deliverable(data: dict[str, Any]) -> NoGoDeliverable:
    """Reject intake missing any required field. Raises NoGoValidationError."""
    if not isinstance(data, dict):
        raise NoGoValidationError(f"nogo deliverable intake must be a dict, got {type(data).__name__}")

    missing: list[str] = []
    decision_id = _require_str(data, "decision_id", missing)
    unlock_condition = _require_str(data, "unlock_condition", missing)
    recheck_date = _require_str(data, "recheck_date", missing)
    redirect_use = _require_str(data, "redirect_use", missing)

    if missing:
        raise NoGoValidationError(
            f"nogo deliverable missing required field(s): {', '.join(missing)}"
        )

    try:
        parsed_date = date.fromisoformat(recheck_date)
    except ValueError as exc:
        raise NoGoValidationError(
            f"recheck_date {recheck_date!r} is not an ISO date (YYYY-MM-DD)"
        ) from exc
    if parsed_date < datetime.now().date():
        raise NoGoValidationError(
            f"recheck_date {recheck_date!r} is in the past — a no-go must recheck forward, not backward"
        )

    lowered = unlock_condition.lower()
    if any(phrase in lowered for phrase in _VAGUE_PHRASES):
        raise NoGoValidationError(
            f"unlock_condition {unlock_condition!r} reads as vague — name a metric, "
            f"threshold, or event that can be checked mechanically"
        )
    if not _CHECKABLE_HINTS.search(unlock_condition):
        raise NoGoValidationError(
            f"unlock_condition {unlock_condition!r} has no checkable threshold "
            f"(number, comparator, $, %, or a duration) — Watcher can't evaluate prose"
        )

    return NoGoDeliverable(
        decision_id=decision_id,
        unlock_condition=unlock_condition,
        recheck_date=recheck_date,
        redirect_use=redirect_use,
        reason=str(data.get("reason", "")).strip(),
    )
