# No-Go Deliverable Schema

CEO-internal, not a standalone agent. `nogo_deliverable.py` defines the
record a **Closer** kill resolution must produce and a **Watcher** monitors:

- `decision_id` — reference to the decision being killed
- `unlock_condition` — must contain a checkable threshold (number, `$`, `%`,
  comparator, or duration) — validator rejects vague prose like "if things
  improve"
- `recheck_date` — ISO date, must be in the future at intake time
- `redirect_use` — where the freed resources go
- `reason` — optional free-text context

`validate_nogo_deliverable(data: dict) -> NoGoDeliverable` raises
`NoGoValidationError` naming every missing/invalid field. No silent partial
acceptance.

Status: **implemented**, 20 tests passing (`python3 -m pytest test_nogo_deliverable.py`).
