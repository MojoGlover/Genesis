# Adversary

CEO subordinate. Forces the CEO to argue against his own decision before it
becomes final.

No LLM — the grid's cloud API policy requires an Accountant spend gate that
doesn't exist yet (`cmptrblk/CLAUDE.md`), and this doesn't need one. Instead
`generate_counter_case()` runs a fixed 5-category failure-mode checklist
(reversibility, resource contention, unvalidated assumption, opportunity
cost, timing/urgency) against the CEO's own `reasoning` text and ranks
categories by how few of their keywords appear — the least-defended category
becomes the "strongest case against," rendered into a decision-specific
sentence naming the actual `proposal`.

State machine: `draft -> contested -> final`.

- `contest(decision)` — generates the counter-cases, `draft -> contested`
- `rebut(decision, text, referenced_ids)` — records a rebuttal; rejects empty
  text or references to unknown counter-case ids
- `finalize(decision)` — `contested -> final`; **blocks unless the rebuttal
  references the single strongest (least-defended) counter-case specifically**,
  not just any of the five

```
python main.py --decision decision.json [--rebuttal rebuttal.json]
```

`decision.json`: `decision_id, proposal, reasoning`.
`rebuttal.json`: `text, references` (list of counter-case ids).

Status: **implemented**, 11 tests passing (`python3 -m pytest tests/`).
Known limitation: the gate is mechanical (did the rebuttal reference the
right id), not semantic (did the rebuttal actually answer it) — see
`test_generic_rebuttal_text_still_requires_real_reference` for the documented
boundary. Judging rebuttal *substance* is the kind of call this repo's
policy reserves for a real LLM pass, not a keyword heuristic.
