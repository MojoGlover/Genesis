# Team Template — cranking out agent teams

> Extracted 2026-07-17 from Karma KaMillion (the first team built this
> way). Goal per Darnie: each new team should be faster to stand up than
> the last. When you improve the pattern for a new team, update THIS file
> — the template is the product, individual teams are instances.

## The shape of a team

```
GENESIS/agents/<team_name>/
├── TEAM.md              ← team source of truth (mission, roster, status,
│                          open items, graduation checklist)
├── .env                 ← team-shared secrets (gitignored — VERIFY with
│                          `git check-ignore` before writing any token)
└── <member_name>/       ← one dir per member, self-contained
    ├── main.py          ← CLI entry: --dry-run, --config, --output
    ├── config.yaml      ← ALL tunables here, none in code
    ├── .env.example     ← documented; real .env gitignored
    ├── .gitignore
    ├── requirements.txt
    └── tests/           ← at minimum, the scoring/decision core
```

## Rules that made Karma KaMillion work

1. **Proving Ground first.** Members run standalone (CLI/cron) with zero
   grid wiring — no Coordinator, no PlugOps, no Chronicle POST. Solo
   stress-testing comes before integration, always. Building the team's
   Coordinator *is* the graduation step, not the starting point.

2. **Daemon vs. agent — the one decision that matters per member.**
   Default every member to a deterministic Python daemon: cheap, testable,
   no model, no hallucination surface. A member gets stamped from
   BlackZero (LLM loop, mission.txt, bridge, the whole apparatus) ONLY
   when its job genuinely requires judgment. "Fetch and rank by formula"
   is a daemon. "Is this actually good?" is an agent. (Also the lesson of
   the 7b-can't-build-agents finding: don't give reasoning jobs to
   machinery, don't give machinery jobs to reasoning.)

3. **Chronicle-compatible logging from day one.** Structured JSON lines
   with Chronicle's wire schema (`kind/actor/target/object/action/
   outcome/detail`), stdout only while in Proving Ground. Graduation then
   just forwards existing lines — no logging rewrite.

4. **Quota self-gating with a handoff note.** Every member that calls a
   metered/rate-limited API gates itself locally (persisted state if the
   quota is daily) AND carries a comment that Accountant's /spend/check
   replaces this once online. Free tiers are quotas too.

5. **Config-driven everything.** Watchlists, subreddits, thresholds,
   weights — in config.yaml, never in code. Growing a watchlist must
   never mean touching main.py.

6. **External accounts through a team service email**, logged in
   Cerberus's `key_registry.md` External Accounts section at signup time,
   not after. One email per team (pattern: `<team>.botico@gmail.com`).

7. **Secrets:** real values only in `.env` (verify gitignored before
   writing), documented in `.env.example`. Never in config.yaml, never
   in code, never in TEAM.md.

8. **Tests on the pure core.** The scoring/decision function is pure and
   tested. Network I/O is thin and dumb around it.

9. **TEAM.md is mandatory** and written when the team is scaffolded, not
   retroactively. It names: mission (and explicitly marks what's
   unconfirmed), roster with built/planned split, external accounts,
   open items, graduation checklist.

## Graduation (Proving Ground → the grid)

Follows the standard lifecycle (`Botico/BOTICO_CANON.md`,
Genesis → Purgatory → Botico). Team-specific gates:

- Sustained scheduled runs, no quota violations, evidenced by own logs
- Output judged useful by Darnie at least once (a team that runs
  perfectly but produces nothing worth reading has not proven anything)
- Coordinator built; Chronicle ingest wired; KNOWN_AGENTS entry in
  cerberus_policy.py; ports via build_agent.py auto-assignment — never
  hand-picked (port policy)
- Any member being promoted to agent-hood goes through the normal
  BlackZero stamp + the full parity checklist (origin gating,
  capability_self_check, fail-closed from_agent — see
  grid_watchdog R11/R12)

## Standing up team N+1

1. Copy the directory shape above; write TEAM.md first.
2. Create the team service email; log it in the External Accounts
   registry before first API signup.
3. Clone the nearest existing member (Karma KaMillion's crawlers are the
   reference implementations) and gut it to the new platform — the
   logging, quota-gate, config-loading, and CLI scaffolding all carry
   over unchanged.
4. Tests + `--dry-run` green before any real API call.
5. Anything you had to invent that wasn't in this file → add it to this
   file.
