# Hardware Roadmap
**PlugWan (MacBook) Infrastructure Plan**
*Last updated: 2026-05-27*

---

## Current State

- **Machine:** MacBook (64GB unified memory)
- **Role:** Grid authority — all inference, all agents, all storage
- **Model in production:** qwen2.5-coder:14b (~8.6GB VRAM, fits cleanly)
- **Status:** Adequate. Not comfortable.

---

## The Identified Next Move

**EVO-X2 class machine — 128GB unified memory.**

This is the correct next infrastructure step. Not a maybe, not aspirational — it's the right call for what the system needs to become. The question is timing, not direction.

128GB unlocks:
- 70B-class model resident (no load/unload cycles)
- Small router model + creative model + 14b simultaneously without memory pressure
- Full agent ecosystem running without competing for VRAM
- Comfortable headroom for growth

---

## Trigger Conditions

**Do not buy until at least one of the following is true:**

1. **Sustained performance pain for 2+ consecutive weeks** — not occasional slowness, not one bad session. Consistent, workflow-blocking degradation that makes work materially harder.
2. **Tax tool or equivalent produces reliable income** — the proof-of-concept loop closes and cash flow justifies the spend.
3. **64GB becomes architecturally blocking** — a specific capability we need is genuinely impossible at 64GB, not just slower.

**Impulse buys are not the move.** The current setup is functional. Buying on frustration locks in a large spend before the income side is established.

---

## What Does NOT Trigger a Buy

- A single slow session
- Wanting to run a bigger model "just to try"
- WWDC announcements (research them, don't react to them)
- Feeling like the tools are inadequate (they're not — the work is the constraint, not the hardware)

---

## WWDC Watch Item

M5 Mac Mini announcements expected mid-2026. Research when available — do not pre-order. Understand the memory/performance curve before deciding between Mac Mini and MacBook Pro class. The EVO-X2 target may be better served by one form factor than the other.

---

## Decision Authority

This purchase requires both trigger conditions above AND explicit sign-off. No autonomous agent action on hardware purchases. This is a human decision with human money.

---

## Deferred (Do Not Revisit Until Trigger Fires)

- ❌ Hetzner GPU server (€184/month) — contradicts conservative posture, adds recurring cost before income
- ❌ Any cloud GPU (RunPod, Lambda, etc.) — capacity unreliable, cost unpredictable
- ❌ Buying today — wait for the trigger
