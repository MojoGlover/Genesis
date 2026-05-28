# PLUGOPS — Plug Network Operations
**v2.0 — Local-First Posture**
*Last updated: 2026-05-27*

---

## Architecture Shift (v1 → v2)

v1 was cloud-primary: agents ran on Cloud Run, PlugWan was a local outlet.

v2 inverts this. **PlugWan is the grid authority.** Cloud is optional infrastructure added later under explicit restrictions. This change was made because cloud costs are unpredictable, cloud-primary architecture adds latency and complexity before the system has proven its value, and the hardware on PlugWan is sufficient.

---

## Plug Categories

**Plugwan** — the local grid authority. Where everything runs.

**Plugouts** — always-on external nodes. Lightweight coordination only, no inference. There is one active plugout at a time. PlugFoe replaced PlugOh as the active plugout. PlugOh is retired.

**Plugclients** — intermittent client devices. No server-side role.

---

## Plug Inventory

### PlugWan (MacBook) — Grid Authority
**Role:** Primary inference, all agent execution, all storage, source of truth.

- Runs all LLM inference via Ollama (local models only)
- Hosts Engineer0 and all active agents
- All agent output originates here
- Must be awake for any real work to happen
- Target: always-on configuration (caffeinate, process-preserving screen lock)

**Model tier running here:**
- Small router model (always resident, routing and coordination)
- Creative small model (always resident, Noodle's brain)
- qwen2.5-coder:14b (Engineer0's primary, always resident)
- 70B-class reasoning model (loaded on demand for deep work only)

**What does NOT run here:** cloud API calls during normal operation. Any cloud API spend requires Accountant approval.

---

### PlugFoe (Hetzner VPS — 178.105.62.143) — Active Plugout
**Role:** Always-on lightweight coordination. No inference. Replaced PlugOh.

Runs:
- Agent registry and heartbeats
- Message queue and agent-to-agent coordination bus
- Stock response layer for MadJanet (see below)
- Routing and presence signals

Does NOT run:
- Any LLM inference
- Any model weights
- Any agent that requires thinking

Cost: Fixed VPS cost, acceptable. No inference cost.

**MadJanet coordination path:** MadJanet routes inter-agent communication and bus messages through PlugFoe by choice. When PlugWan is awake, she uses PlugFoe to reach Engineer0, Cerberus, and other agents. When PlugWan is asleep, PlugFoe's pattern matcher returns an honest holding response. Default catch-all: *"Heard you. This one needs real thinking so it'll have to wait until the laptop's awake."* Zero inference, zero API cost.

**Note:** The Botico app currently still points at PlugOh (Cloud Run) for registry/bus — this is why agents show "unknown" in the UI. Needs to be updated to point at PlugFoe.

---

### PlugOh (Cloud Run) — Retired Plugout
**Role:** Previous active plugout. Replaced by PlugFoe.

Cloud Run costs nothing when idle. Parked indefinitely. Do not deploy to it without an explicit posture change decision. The Botico app still references it — updating that reference to PlugFoe is a pending task.

---

### PlugoCinco (RunPod) — Deferred
**Role:** GPU cloud for art models and image inference. On-demand only.

Status: Deferred — not just for cost, but because capacity is unreliable. The entire fleet was sold out during the last attempt. Do not build anything that depends on RunPod availability. When needed: spin up on demand, verify availability first, tear down after.

---

### PlugToo (Teclast tablet) — Intermittent Client
**Role:** Mobile client only. No server-side role.

---

### PlugTree (iPhone) — Intermittent Client
**Role:** Mobile client and notification endpoint. No server-side role.

Notification path for PlugWan events (task completions, agent alerts) routes through PlugTree via Pushover or ntfy.

---

## Inference Policy

**All inference is local by default.**

1. Ollama on PlugWan handles all model calls
2. No cloud API calls without Accountant approval
3. Expensive APIs (GPT-4 class, Claude Opus) are off the table
4. Haiku-class APIs may be approved for conversational polish only — requires explicit per-agent decision, not a standing permission

---

## Cost Policy

Any spend — API calls, cloud compute, new services — requires either:
- Accountant approval (for recurring or significant one-time cost), or
- Explicit sign-off from Darnie

Agents do not authorize their own spending. This is a hard rule.

---

## What Changed from v1

1. PlugWan promoted from local outlet → grid authority
2. PlugOh retired — replaced by PlugFoe as the active plugout
3. PlugFoe is the active plugout: coordinator only, no inference
4. MadJanet coordination path clarified: routes inter-agent comms through plugout by choice
5. MadJanet stock response layer added (PlugFoe-hosted, zero inference)
6. PlugoCinco deferred (capacity unreliable, not just cost)
7. All-local inference policy made explicit
8. Cloud API spend gate added (Accountant approval required)
9. Pending: Botico app registry/bus reference needs updating from PlugOh → PlugFoe
