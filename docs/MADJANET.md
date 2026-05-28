# MadJanet — Personal Assistant Agent
**v2.0 — Local-Primary**
*Last updated: 2026-05-27*

---

## Identity

MadJanet is the personal assistant agent in the Computer Black ecosystem. She handles scheduling, communication drafting, reminders, personal logistics, and general assistant tasks. She is not a coding agent and does not make infrastructure decisions.

---

## Architecture Change (v1 → v2)

**v1:** Cloud-primary. MadJanet's inference ran via cloud API (Haiku). PlugWan was a local fallback.

**v2:** Local-primary. MadJanet's inference runs on PlugWan via Ollama. Cloud API is a deferred fallback, not a standing option.

This matches the ecosystem-wide shift to local-first posture. Cloud was primary because it was "always on" — but that reasoning assumed PlugWan wasn't always on. That's being fixed at the infrastructure level (caffeinate, always-on config).

---

## When PlugWan Is Asleep — Stock Response Layer

MadJanet cannot think without PlugWan. Rather than going silent or failing silently, a stock response layer runs on PlugFoe (Hetzner).

**How it works:**
- Incoming messages hit PlugFoe's pattern matcher
- Pattern matcher identifies message type (question, task, casual, urgent)
- Returns an honest holding response — no inference, no API call
- Default catch-all: *"Heard you. This one needs real thinking so it'll have to wait until the laptop's awake."*
- More specific patterns (e.g., scheduling request, reminder) return more specific holding responses
- No fabrication. No pretending to have processed anything.

**What this is not:** A thinking layer. The stock response layer does not answer questions, make decisions, or act on tasks. It acknowledges and holds.

---

## Model

- **Primary:** Small conversational model via Ollama on PlugWan (TBD — to be set when MadJanet's grounding files are written)
- **Conversational polish:** Haiku-class API may be approved for specific use cases — requires explicit decision, not standing permission
- **Expensive APIs:** Off the table

---

## Hosting

| Component | Location |
|---|---|
| Primary inference | PlugWan (Ollama) |
| Stock response layer | PlugFoe (Hetzner) |
| Registry / heartbeat | PlugFoe |
| Mobile interface | PlugTree (iPhone) / PlugToo (Teclast) |

---

## Boundaries

MadJanet does not:
- Make infrastructure decisions
- Approve spending
- Write or deploy code
- Access other agents' workspaces
- Operate when PlugWan is asleep (beyond stock holding responses)

---

## Status

MadJanet is listed as online but her grounding files have not been fully written for the v2 local-primary configuration. The stock response layer on PlugFoe is not yet built. Both are Phase 4 work, gated on the tax tool proof-of-concept loop closing first.
