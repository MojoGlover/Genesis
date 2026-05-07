# API Key Rotation Protocol
Computer Black — Security Operations

**Owner:** Cerberus (enforcement) + Concierge (execution)  
**Authority:** Cerberus approves all rotation schedules. Concierge executes rotations.  
**Review cycle:** Cerberus audits compliance monthly.

---

## Why This Exists

API keys are the most common attack surface for a cloud-native AI operation.
A leaked key with no rotation window is a liability that never expires.
Regular rotation limits the damage window even if a key is silently compromised.

---

## Rotation Schedule (Standard)

| Tier | Rotation Interval | Examples |
|------|------------------|---------|
| **Critical** — payment or account access | 30 days | Stripe, PayPal, bank integrations |
| **High** — AI inference APIs | 60 days | Anthropic, OpenAI, Groq, Replicate, ElevenLabs |
| **Medium** — platform/infrastructure | 90 days | RunPod, Hetzner, GCP, GitHub |
| **Low** — read-only or analytics | 180 days | Monitoring, analytics, webhook tokens |

Rotation interval is the **maximum** time a key may live. Rotate earlier if:
- A key was shared with any person or system outside Computer Black
- A key appeared in any log, error message, or git commit
- Cerberus flags a suspicious usage pattern
- Any agent using the key is decommissioned

---

## Rotation Procedure

**Step 1 — Concierge generates new key**
- Log into the provider's dashboard
- Generate a new key *before* revoking the old one
- Record the new key immediately in the vault under the same service name, appended with `-pending`

**Step 2 — Concierge updates all consumers**
- Identify every agent and system using the key (Cerberus maintains this registry)
- Update each consumer's config or environment with the new key
- Confirm each consumer restarts and connects successfully

**Step 3 — Cerberus validates**
- Cerberus runs an integrity check on each updated agent
- Confirms no consumer is still referencing the old key in config or environment
- Confirms new key authenticates correctly (test call)

**Step 4 — Revoke old key**
- Only after Step 3 passes: Concierge revokes the old key at the provider
- Remove the `-pending` suffix from vault entry
- Log the rotation in the audit trail: timestamp, service, rotating agent, approving agent

**Step 5 — Accountant records**
- Accountant notes the rotation in the cost ledger (some providers bill per key or per rotation)
- Confirms billing continues uninterrupted on the new key

---

## Emergency Rotation (Immediate)

Triggered by: suspected compromise, accidental exposure, agent breach.

1. Cerberus issues emergency rotation order to Concierge
2. Concierge generates new key immediately — no scheduled window
3. Old key revoked **before** consumers are updated (accept brief downtime)
4. Cerberus notifies Darnie with: what was compromised, what was revoked, blast radius assessment
5. All agents using the key are suspended until they confirm the new key
6. Full audit of access logs for the compromised key period

---

## Key Registry

Cerberus maintains the canonical list of all active API keys:
- Service name
- Tier (Critical / High / Medium / Low)
- Date last rotated
- Next rotation due
- Which agents consume it
- Vault entry name

This registry is stored in: `/Users/darnieglover/ai/cmptrblk/Cerberus/knowledge/key_registry.md`
Updated by Concierge after every rotation. Audited by Cerberus monthly.

---

## Vault Storage Convention

All keys stored in Cerberus vault using this naming pattern:

```
{SERVICE}_{KEY_TYPE}
```

Examples:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `RUNPOD_API_KEY`
- `REPLICATE_API_KEY`
- `ELEVENLABS_API_KEY`
- `GCP_SERVICE_ACCOUNT_KEY`
- `GITHUB_PAT`

Pending keys (during rotation, before old key is revoked):
- `ANTHROPIC_API_KEY_PENDING`

---

## Non-Compliance

If a key is found past its rotation due date:
- Cerberus flags it and notifies Darnie
- Cerberus initiates rotation via Concierge without waiting for a request
- The reason for the delay is logged

Keys do not get extensions. The schedule is the schedule.
