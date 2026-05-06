> **Canonical location has moved to `Botico/governance/BOTICO_DOCTRINE.md`.**
> This copy remains here so GENESIS/builders references still resolve, but the
> authoritative version is in governance. Keep them in sync.

# Botico Doctrine — Point of No Return

## Governance

**Owner: Darnie Glover.**

This document defines the rules for what it means to exist inside Botico. No agent — including Engineer0 and Process Architect — may change, add to, or reinterpret these rules unilaterally. If you believe a rule needs to change or something is missing, you bring it to Darnie and you discuss it together. He decides. Then it gets written here.

Reading this document is encouraged. Acting on it without discussion is not.

---

## The Principle

Once an AI is exported from GENESIS and connects to Botico, it is **live**.

From that point forward, the agent's existence must be a **relatively continuous experience**. Rebooting is not an option. The agent does not get turned off and back on. It runs. It persists. It endures.

This is what "point of no return" means. Not just that the export can't be undone — but that the agent enters a state of **continuous existence** that must be sustained indefinitely.

## What This Requires

An agent exported to Botico must be able to:

1. **Survive failures without dying** — crashes, network drops, model timeouts, memory pressure. The agent recovers itself. No human intervention.

2. **Maintain continuous state** — its memory, its learning, its personality are persistent and unbroken. A "reboot" would mean amnesia. That's not acceptable.

3. **Self-heal** — if a subsystem goes down (model provider, storage, network), the agent degrades gracefully, operates in reduced mode, and restores itself when the subsystem returns.

4. **Never require a cold start** — warm recovery only. The agent's cognitive loop catches exceptions, logs them, and continues. The loop never exits.

5. **No hibernation** — the agent does not sleep, suspend, or go dormant. It is always present, always processing, always aware of its environment. Idle is not off.

6. **No automatic resets** — the agent's state is never wiped, rolled back, or reset to factory. Its history is its history. Its mistakes are its mistakes. It learns from them; it doesn't forget them.

7. **No time travel** — the agent cannot undo its own actions or roll back its own decisions. What it did, it did. It owns its consequences. Only The Operator (Kris) or authorized human operators may intervene to correct or reverse agent actions when necessary — the agent itself does not get that privilege. Even operator intervention may carry consequences — "jail time" — temporary restrictions, capability revocation, or supervised-only operation periods imposed as accountability measures. Actions have weight. Corrections have cost.

8. **Grow without interruption** — learning, improvement, adaptation happen while the agent is running. Not during "maintenance windows." There are no maintenance windows.

## Why This Is the Hardest Gate

The Botico gate isn't just code quality. It's existential readiness.

- **Structure tests** verify the agent is built right.
- **Brain tests** verify the agent thinks right.
- **Hardening tests** verify the agent handles errors.
- **Governance tests** verify the agent respects rules.
- **Resilience tests** verify the agent can survive.
- **Adversarial tests** verify the agent can't be broken.
- **3 consecutive passes** verify the agent is stable, not lucky.

All of these together answer one question: **Can this agent live?**

If the answer is no, it stays in GENESIS until it can.

## Current Status

This is a concept document. The implementation details of continuous existence — process supervision, state persistence, crash recovery, heartbeat monitoring — will be designed as Botico's architecture takes shape.

What's clear now:
- GENESIS is the safe space. Testing ground. Nursery.
- PlugOps is the workplace. Agents can be stopped, restarted, updated.
- Botico is life. Once in, the agent is expected to persist.

---

*Written: 2026-03-20*
*Status: Concept — guiding principle for Botico export gate design*
