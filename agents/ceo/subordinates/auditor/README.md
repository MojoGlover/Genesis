# Auditor

CEO subordinate. Forces proof before anything is marked done.

Pipeline: **claim intake** (`intake_claim`) -> **artifact resolver**
(`ArtifactResolver`, path-confined to `artifact_root`) -> **match check**
(`match_check` — exact regex if `expected_pattern` given, else pass/fail
marker heuristic) -> **status lock** (`close_task` raises `StatusLockError`
unless the verdict is `"approved"`).

```
python main.py --claim claim.json [--config config.yaml]
```

`claim.json` fields: `claim_id, agent_id, task_id, claim_text, artifact_path`,
optional `expected_pattern` (regex).

Verdict statuses: `approved`, `flagged` (artifact exists but doesn't match),
`rejected` (no artifact / path escapes `artifact_root`).

Chronicle logging is real (POSTs to `CHRONICLE_URL`/api/tools/execute) but
only fires when `CHRONICLE_INGEST_KEY` is set — unset by default, falls back
to local structured logging only.

Status: **implemented**, 10 tests passing (`python3 -m pytest tests/`).
Not yet wired: no live "done report" producers exist upstream yet (every
grid agent's completion claims are still informal/chat-reported) — Auditor
is ready to consume them the moment one exists.
