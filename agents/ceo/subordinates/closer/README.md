# Closer

CEO subordinate. Forces a binary call on every open thread past deadline:
**commit** (new resources/timeline) or **kill** (produces a no-go
deliverable). No third option.

- `track(item_id, title, deadline)` — register a tracked thread
- `list_overdue(threads, now=None)` — escalation: open threads past `deadline`
- `resolve_commit(thread, new_deadline, new_resources)` — requires a real
  future deadline and a non-empty resources statement
- `resolve_kill(thread, nogo_data)` — validates against
  [`ceo/schemas/nogo_deliverable.py`](../../schemas/README.md) (imported
  directly, not duplicated — Watcher reads the same schema)
- `resolve(thread, resolution)` — dispatches on `resolution["type"]`;
  anything besides `"commit"`/`"kill"` is rejected
- Already-resolved threads reject a second resolution (no silent overwrite)

```
python main.py --threads threads.json [--resolve resolution.json]
```

Status: **implemented**, 13 tests passing (`python3 -m pytest tests/`).
Not yet wired: nothing calls `list_overdue()` on a schedule — it's a library
function today, not a cron job. Needs a scheduler once CEO itself runs a
loop.
