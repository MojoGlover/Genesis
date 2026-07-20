# Watcher

CEO subordinate. Monitors killed decisions so they don't silently become
permanent. **Never auto-reverses** — it only surfaces a resurrection
candidate; reopening a decision is a CEO/Closer/Adversary call, not
Watcher's.

- `NoGoLedger` — JSON-Lines store of killed decisions, validated against
  [`ceo/schemas/nogo_deliverable.py`](../../schemas/README.md) on intake
  (`.add()`), rejects duplicate `decision_id`
- `evaluate_entry(entry, data_source, now)` — returns `dormant` (before
  `recheck_date`), `watching` (due, condition not yet met), `triggered`
  (condition met), or `degraded`
- `parse_condition(text)` — extracts `(metric, comparator, threshold)` from
  `unlock_condition` text via a keyword/regex parser; returns `None` if the
  condition isn't mechanically checkable
- `monitor(ledger, data_source, now)` — evaluates every entry, returns only
  the ones **newly** surfaced this pass (idempotent — an entry is surfaced
  once, not re-alerted every poll)

**Accountant doesn't exist yet.** `_load_accountant_data()` reads a flat
JSON metric snapshot from `ACCOUNTANT_LEDGER_PATH` as a stand-in. Missing
data, an unparseable condition, or a metric absent from the snapshot all
degrade the entry to `"degraded"` rather than guessing — a no-go with no
reliable data source stays surfaced-as-unresolvable, it never falsely
triggers. Swap `_load_accountant_data()` for a real Accountant client the
day that service exists.

```
python main.py --add nogo.json --ledger ledger.jsonl      # intake a kill
python main.py --ledger ledger.jsonl --data snapshot.json # run one monitor pass
```

Status: **implemented**, 14 tests passing (`python3 -m pytest tests/`).
Not yet wired: no scheduler runs `monitor()` periodically, and
`ACCOUNTANT_LEDGER_PATH` has no real producer since Accountant isn't built —
every poll will degrade until that exists.
