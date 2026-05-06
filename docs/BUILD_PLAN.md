# Computer Black — Foundation Build Plan

Written 2026-04-23. Updated 2026-05-03 (federated PlugOps + transporter model).
Resumable across sessions and models.

## Context

Darnie's agent grid is fragile because foundational primitives were never built
cleanly — everything was layered on ad-hoc infrastructure. This plan builds the
foundations in GENESIS, stress-tests each, and seals them into Botico.

Governing rules: [genesis_rules.md](./genesis_rules.md) (v1.2, Rules 21 & 22
especially).

---

## Architectural model: Federated PlugOps + Transporter

PlugOps is **not** one server in the cloud. It runs everywhere agents run.

### Two roles

- **Primary PlugOps** (Hetzner or GCP) — control plane.
  - Owns the canonical agent registry
  - Holds policy authority (Cerberus rulings are final here)
  - Holds the ledger-of-record (cost accounting)
  - Hosts the chat console / dashboard
  - Authorizes inter-instance migrations
- **Satellite PlugOps** (laptop, tablet, iPhone, RunPod, any other server) — data plane + sandbox.
  - Caches the registry locally
  - Sandboxes its agents — they can ONLY reach peers / outside world / Kris through this PlugOps
  - Runs the local message bus (communication module)
  - Forwards control-plane traffic to primary
  - Survives primary outages: local agents keep running, just can't cross instances or reach outside

### The cage / sandbox property

Agents on a satellite PlugOps cannot:
- Open arbitrary network sockets
- Reach other agents except through the local PlugOps bus
- Call external APIs except through PlugOps' tool_bus / model_gateway
- Discover peers except through the cached registry

This makes PlugOps the **security boundary**, not a policy promise. It's also what
makes math-agent diagnostics meaningful — if a math agent reports a peer
unreachable, no other path was available to mask the failure.

### The transporter

The Accountant manages cost and quota by **moving agents between PlugOps instances**.

Use cases:
- Free tier exhausted on RunPod → migrate Goldberg to local plugfoe (Hetzner)
- Tablet asleep → temporarily host MadJanet on grid
- Heavy compute job → spin up Plug5 (RunPod), migrate the agent there for the job, migrate back when done
- Cost optimization → shuffle agents toward whatever instance has the cheapest budget right now

This requires:
1. **Mind state externalization** (module #3) so the agent can be paused, serialized, restored.
2. **Migration protocol** in the registry (module #2) — single-instance lock, source-pause → state-handoff → destination-resume → source-release.
3. **Migration trust gate** — Accountant refuses to migrate to/from any PlugOps instance that hasn't passed a recent math-agent migration test (formal property of the Registry).

Agents do not know they were moved. They wake up on the new host and resume.

---

## Status legend

- ✅ done
- 🔬 in GENESIS, validating
- 🔒 sealed in Botico
- ⏳ planned

## Foundational modules (build order)

| # | Module | Location | Status | Notes |
|---|---|---|---|---|
| 1 | communication | `GENESIS/modules/communication/` | 🔬 | Smoke test passed (500 iters, 0 errors, p50 3ms). Needs long stress run (~1M iters) before sealing. Single-node hub. |
| 1.5 | **federation** | — | ⏳ | Inter-PlugOps routing. Sits on top of comm. Peer discovery, auth between PlugOps instances, partition handling, registry sync (satellite cache ↔ primary truth). Required before math agents can fully exercise the mesh. |
| 2 | registry | — | ⏳ | Agent identity, liveness, single-instance enforcement, **migration_trust property per PlugOps instance**. First module after federation. |
| 3 | mind_state | — | ⏳ | Externalized per-agent state. Prereq for Agent Hospital AND for the transporter — without externalized state, agents cannot be moved. |
| 4 | supervisor | — | ⏳ | Process lifecycle. Replaces `nohup &` / ad-hoc launchd. Implements pause/resume primitives needed for migration. |
| 5 | policy_gate | — | ⏳ | Cerberus — allow/deny/approve. On primary = authoritative; on satellites = forwards to primary for any non-cached decision. |
| 6 | tool_bus | — | ⏳ | Controlled gateway for external actions. The cage's "exit door" for tool calls. |
| 7 | ledger | — | ⏳ | Action + cost recording, budgets (the economy). On primary = ledger-of-record; satellites stream events upstream. **Tags** every record (`category=diagnostic`/`real`/etc.) so cost reports stay honest. |
| 8 | scheduler | — | ⏳ | Cron + event triggers — the heartbeat. Per-instance, but jobs can target other instances via federation. |
| 9 | observability | — | ⏳ | Structured logs, unified view. Aggregates from all satellites to primary. |
| 10 | model_gateway | — | ⏳ | Centralized LLM API calls (OpenAI/Gemini/Ollama/etc.). Agents ask by role, not provider — keeps agent identity independent of any vendor. Single place for metering (→ ledger), key storage, retry/fallback, prompt caching, policy inspection (→ policy_gate). Pattern: "LiteLLM-style proxy." |

## Diagnostic agents

| Agent family | Location | Status | Notes |
|---|---|---|---|
| Math agents | `GENESIS/agents/math_agents/` | ⏳ | Lightweight stubs. One per PlugOps instance. 30s tick, send `a+b` to peer math agent at another instance, record round-trip. Spec: [`agents/math_agents/SPEC.md`](../agents/math_agents/SPEC.md). Blocks on Federation (#1.5). Test #5 (migration) further blocks on Supervisor (#4) + Mind State (#3). |

## Parallel/adjacent work

| Task | Status | Notes |
|---|---|---|
| Janitor (clean `~/ai`, skip `cmptrblk/`) | ⏳ | Dry-run report → quarantine to `~/ai/.trash/<date>/`. Never auto-trash notes/concepts. First attempt by Engineer0 failed (hallucinated output). Claude should build directly. |
| Stale-docs sweep | ⏳ | `PORT_CONFLICT_GUIDE.md` at `~/ai/` is wrong (says 7860/9000, actual is 5001+). Either delete or rewrite. |
| BlackZero audit | ⏳ | Engineer0 has a reproducible ReAct hallucination bug: fabricates tool results. Fix must land in `GENESIS/BlackZero/` per feedback memory, then propagate. Do AFTER modules 2-3 to know what BlackZero needs to support (especially mind state externalization). |
| `cmptrblk/CLAUDE.md` reconciliation | ⏳ | Master CLAUDE.md shows all 10 modules sealed at v1 with ports 9100-9109. That's aspirational — actual state per this plan is only #1 in validation. Either rewrite CLAUDE.md to reflect reality or mark its module table as "target state." |
| README + doctor.py update | ⏳ | Per Rule 19, both must reflect rules v1.2 (Rules 21 & 22). |

## Graduation procedure (GENESIS → Botico)

When a module passes stress validation:

1. Copy `GENESIS/modules/<name>/` → `Botico/modules/<name>/v1/`
2. Write `SEALED` file with: version, date, SHA256 tree of contents, GENESIS git commit
3. `chmod -R a-w Botico/modules/<name>/v1/`
4. Update any agent configs to pin the new version
5. Leave `GENESIS/modules/<name>/` in place for future changes (new cycle → v2)

See [Botico/modules/README.md](../../Botico/modules/README.md) for the sealing rules.

## Immediate next actions (in order)

1. **Darnie:** run `cd cmptrblk/GENESIS/evals/communication_stress && ./run_stress.sh 1000000` overnight. Report final counters.
2. **Claude:** if counters clean, write seal-and-ship script and graduate Comm to `Botico/modules/communication/v1/`.
3. **Claude:** build Janitor directly (do not delegate to Engineer0 again until BlackZero is fixed).
4. **Claude:** build `federation` module (#1.5) in GENESIS — at minimum, two-node forwarding so a message from `instance-A:agent-X` reaches `instance-B:agent-Y` cleanly.
5. **Claude:** build `registry` module (#2) with migration_trust property hooks.
6. **Claude:** scaffold math agent stubs in `GENESIS/agents/math_agents/` — they unblock validating federation.
7. Continue down the foundation list.

## Known hazards

- Engineer0 cannot be trusted with multi-file build tasks right now (fabricates tool output). Reproduced twice. Do not delegate real work to it until BlackZero ReAct loop is fixed.
- `~/ai/PORT_CONFLICT_GUIDE.md` contradicts current port assignments — misleads future sessions.
- `cmptrblk/CLAUDE.md` claims 10 modules sealed; this plan is the truth — only #1 is in validation.
- Rule 19 compliance pending: README.md and doctor.py not yet updated for rules v1.2.
- Math agents spec assumes inter-PlugOps routing exists. Federation module must land before Test #2 onward.
