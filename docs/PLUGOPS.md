# PLUGOPS — Plug Network Operations
**v2.0 — Local-First Posture**
*Last updated: 2026-05-27*

---

## Architecture Shift (v1 → v2)

v1 was cloud-primary: agents ran on Cloud Run, PlugWan was a local outlet.

v2 inverts this. **PlugWan is the grid authority.** Cloud is optional infrastructure added later under explicit restrictions. This change was made because cloud costs are unpredictable, cloud-primary architecture adds latency and complexity before the system has proven its value, and the hardware on PlugWan is sufficient.

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

### PlugFoe (Hetzner VPS — 178.105.62.143) — Coordinator Only
**Role:** Always-on lightweight coordination. No inference.

Runs:
- Agent registry and heartbeats
- Message queue for inter-agent coordination
- Stock response layer for MadJanet (see below)
- Routing and presence signals

Does NOT run:
- Any LLM inference
- Any model weights
- Any agent that requires thinking

Cost: Fixed VPS cost, acceptable. No inference cost.

**MadJanet stock response layer:** When PlugWan is asleep and MadJanet receives a message, PlugFoe's pattern matcher returns an honest holding response. Default catch-all: *"Heard you. This one needs real thinking so it'll have to wait until the laptop's awake."* Zero inference, zero API cost.

---

### PlugOh (Cloud Run) — Dormant
**Role:** Reserved. Do not deploy to without an explicit decision to change posture.

Cloud Run costs nothing when idle. It stays parked. If the architecture ever shifts back toward cloud-primary (requires an explicit posture change decision), PlugOh is the deployment target. Until then, treat as non-existent.

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
2. PlugOh demoted from active deployment → dormant/reserved
3. PlugFoe role clarified: coordinator only, no inference
4. MadJanet stock response layer added (PlugFoe-hosted)
5. PlugoCinco deferred (capacity unreliable, not just cost)
6. All-local inference policy made explicit
7. Cloud API spend gate added (Accountant approval required)
