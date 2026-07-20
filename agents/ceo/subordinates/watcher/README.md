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

**Accountant is live** (Danika Franklin, `Botico/agents/accountant`, port
5002). `fetch_accountant_snapshot()` calls her Tool Bus endpoint
(`POST /api/tools/execute`, tool `"ledger_budget"`, `X-Agent-Id` header —
the same pattern every grid agent uses to borrow another agent's tools) per
`ACCOUNTANT_WATCHED_AGENTS`, and flattens each response into
`{agent_id}_spend_usd` / `_pct_used` / `_remaining_usd` / `_cap_usd` metrics.
Her actual ledger backend is `model_gateway` (port 9109) — if that's down,
if Accountant herself is unreachable, or if a condition is unparseable or
names a metric outside the fetched snapshot, the entry degrades to
`"degraded"` rather than guessing. Never a false trigger. `ACCOUNTANT_LEDGER_PATH`
remains as a manual override for offline testing or when the live call isn't wanted.

```
python main.py --add nogo.json --ledger ledger.jsonl        # intake a kill
python main.py --ledger ledger.jsonl                        # live Accountant call
python main.py --ledger ledger.jsonl --data snapshot.json   # override with a local snapshot
```

Status: **implemented**, 18 tests passing (`python3 -m pytest tests/`), and
verified end-to-end live 2026-07-20 against real data
(`fetch_accountant_snapshot("http://localhost:5002", ["engineer0"])` returned
real `spend_in_window_usd`/`pct_used`/`remaining_usd`/`cap_usd`). No Tailscale
needed — Accountant's `model_gateway` backend (port 9109) runs locally
alongside her, same host. It just wasn't running the first time this was
checked (no launchd job existed for it yet); now started via
`~/Library/LaunchAgents/com.cmptrblk.mod.model_gateway.plist`
(`RunAtLoad`+`KeepAlive`, same pattern as Accountant/Engineer0/Cerberus).
Not yet wired: no scheduler runs `monitor()` periodically.
