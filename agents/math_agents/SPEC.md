# Math Agents — PlugOps Diagnostic Stubs

**Status:** Validated spec, ready to scaffold once Federation module (#1.5) lands.
**Owner:** Kris (MojoGlover / Computer Black)
**Last updated:** 2026-05-03
**Location:** GENESIS — `agents/math_agents/`
**Graduates to:** Botico when stable
**Depends on:** federation (#1.5), registry (#2), mind_state (#3), supervisor (#4)

---

## Purpose

Math agents are lightweight diagnostic agent stubs that ship with every PlugOps
deployment (primary + every satellite). Their job is **not** to do meaningful
work — their job is to **prove the PlugOps comms mesh is alive and routing
correctly across instances**.

Four functions:

1. **Liveness check** — every PlugOps instance has at least one math agent. If it goes dark, the instance is degraded.
2. **Routing proof** — math agents send simple messages to peers across instances (PlugWan ↔ grid ↔ PlugToo ↔ PlugTree). Successful round-trips prove the routing layer works end-to-end.
3. **Migration test bed** — real agent instances (not hardcoded diagnostics), so the Accountant can practice migrating them between instances. The safe canary before real agents migrate.
4. **Reachability validation for Kris** — Kris can ping any math agent from any plug and confirm bidirectional comms work from that location.

---

## Architectural decision

**Math agents are lightweight agent stubs, NOT subsystems baked into PlugOps core.**

- Keeps PlugOps core clean — no diagnostic logic mixed into platform code.
- Math agents iterate independently of PlugOps releases.
- Treating them as real agents means migration, registry, and routing logic gets exercised by real agent semantics, not synthetic test paths.
- Reference implementation of "smallest possible agent" for future scaffolding.

PlugOps **launches** them automatically on startup, but does not contain their code.

---

## Subsystems

### 1. Math Agent Core
- **Identity:** `math-{location}-{n}` — e.g. `math-plugwan-0`, `math-grid-0`, `math-plugtoo-0`. ID is by *current location*, not original spawn. After migration, identity is reborn at destination; old ID is reclaimed at source.
- **Behavior:** On a 30-second tick, sends `{"op":"add","a":3,"b":4}` to a peer math agent at another PlugOps instance via the standard message bus.
- **Response:** Receiving math agent computes the result and replies. Sender records round-trip latency and success/failure.
- **State:** Local SQLite (`math_agent.db`) — last 100 round-trips, peer reachability matrix.

### 2. PlugOps auto-launch hook
- On PlugOps startup, **after registry hydrates from primary**, before real agents boot.
- Check registry for a math agent assigned to this instance.
- If none exists, spawn one via the standard agent-launch path (same path real agents use).
- Register it with the grid so it appears in the canonical registry.

### 3. Reachability reporter
- **PlugOps** exposes `/health/mesh` (not the agent — the agent stays inside the cage).
- PlugOps answers by querying its local math agent over the bus.
- Returns: list of peer math agents, last successful contact timestamp per peer, current latency.
- Surfaces to Kris via dashboard or direct query.

### 4. Migration compliance
- Math agents must respond correctly to Accountant migration directives.
- On migration: pause ticks, serialize state via mind_state module, hand off to destination PlugOps, resume.
- The canary — if math agents can't migrate cleanly, no real agent should.
- **Migration trust gate:** every PlugOps instance has a `migration_trust` flag (property of the registry). Flag flips true only after a successful math-agent round-trip migration in the last 24 hours. Accountant refuses to migrate real agents to/from any instance with stale or false trust.

---

## Tests

| # | Test | Pass criteria | Blocks on |
|---|------|---------------|-----------|
| 1 | Single-instance liveness | Math agent starts on PlugOps boot, ticks every 30s | — |
| 2 | Two-instance round-trip | math-grid-0 sends to math-plugwan-0, gets correct reply within 5s | federation (#1.5) |
| 3 | Three-instance fan-out | math-grid-0 successfully reaches all peers in mesh | federation (#1.5) |
| 4 | Peer-down detection | Killing math-plugtoo-0 → grid math agent reports peer unreachable within 90s | federation (#1.5) |
| 5 | Migration | Accountant migrates math-plugwan-0 → grid; ticks resume; peers update routing | mind_state (#3), supervisor (#4), ledger (#7) for migration trigger |
| 6 | Registry sync | New math agent appears in canonical registry within 30s of spawn | registry (#2), federation (#1.5) |
| 7 | Resource judiciousness | No polling tighter than 30s; no API calls beyond mesh peers | — |

---

## Resource judiciousness compliance

Per the **Resource Judiciousness Rule** (non-negotiable):
- Tick interval: 30s (matches Operator heartbeat).
- Messages: tiny JSON payloads (~50 bytes).
- No external API calls. Math agents talk only to peers via PlugOps bus.
- No vehicle wake commands, no cloud-billable operations beyond bus traffic.
- Local SQLite caps at 100 entries (rolling).

The Accountant charges math agents the same flat per-message fee as real agents
(see ledger #7 — same ledger, `category=diagnostic` tag). Total cost is bounded
and visible. If math-agent traffic ever shows up as a non-trivial line item,
that itself is a signal something is wrong.

---

## Resolved open questions (validated 2026-05-03)

1. **Boot order: first or after registry hydrates?**
   **After.** Math agents need peers to validate routing — empty registry = nothing useful to test. Sequence: PlugOps core → registry hydrates from primary → math agent → real agents.

2. **One per instance or configurable?**
   **Exactly one.** More agents on one instance can't tell you anything one can't. Test surface is *between* instances.

3. **Separate billing category?**
   **Same ledger, dimensional tag.** `category=diagnostic`. Cost stays honestly visible; Accountant filters by tag for "real" agent costs; spike in diagnostic spend stands out as its own category in reports.

4. **Math-agent migration first against new instances?**
   **Yes — hard precondition.** Formalized as the `migration_trust` property of the Registry module. Accountant refuses real-agent migration to/from any PlugOps with stale/false trust.

5. **(Added) Identity across migrations.**
   **ID-by-current-location.** `math-{location}-{n}` reflects where the agent IS, not where it was spawned. Migration = identity rebirth. The ID is the diagnostic claim.

---

## Next action

Scaffold `agents/math_agents/` following BlackZero structure once Federation
module (#1.5) lands. Build at the family level (this dir) for shared spec/code,
then per-instance subfolders if behavior diverges (it shouldn't).
