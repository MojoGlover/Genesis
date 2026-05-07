# Temporary Agent Vault Access Protocol
Computer Black — Security Operations

**Owner:** Cerberus (authorization + cleanup enforcement)  
**Vault operator:** Concierge (stores credentials on behalf of authorized agents)  
**Created:** 2026-05-07

---

## What This Covers

Sometimes a task requires a short-lived agent — a scraper, a form-filler, a
one-time researcher — that needs to store a credential, API key, or discovered
information in the vault before it terminates.

Permanent agents (CEO, Accountant, MadJanet, etc.) have standing vault access
through Concierge. Temporary agents do not. This protocol defines how a temp
agent gets authorized, stores its findings, and is cleaned up.

---

## Key Principle

**Temp agents never hold credentials.** They collect or discover information
and hand it to Concierge to store. Cerberus authorizes the handoff.
The temp agent itself holds nothing sensitive after the vault write is complete.

---

## Lifecycle

```
Darnie (or authorized permanent agent)
    → requests temp agent spawn
    → Cerberus issues a scoped token (TTL: task duration, max 4 hours)
    → temp agent spawns with token in environment only (never in config files)
    → temp agent runs its task
    → temp agent calls Concierge: POST /concierge/vault/accept with token + data
    → Concierge validates token with Cerberus
    → Cerberus confirms: token valid, scope matches, not expired
    → Concierge writes to vault
    → temp agent signals completion
    → Cerberus revokes token immediately
    → temp agent terminates
    → Cerberus audits: confirms temp agent is deregistered within 10 minutes
```

---

## Step-by-Step

### Step 1 — Spawn Request

The requesting agent (or Darnie directly) sends to Cerberus:

```
POST http://localhost:8200/temp-agent/authorize
{
  "requested_by": "ceo",           // which permanent agent is requesting
  "task_description": "...",        // human-readable — logged in audit trail
  "vault_scope": ["write"],         // what vault operations are permitted: read | write | list
  "vault_keys": ["SERVICE_NAME"],   // which vault entries may be accessed (whitelist)
  "ttl_seconds": 3600,              // max 14400 (4 hours)
  "agent_id": "temp-scraper-001"   // name the temp agent will register under
}
```

Cerberus responds:
```json
{
  "token": "cbk_tmp_abc123...",
  "expires_at": "2026-05-07T06:00:00Z",
  "agent_id": "temp-scraper-001",
  "scope": ["write"],
  "vault_keys": ["SERVICE_NAME"]
}
```

Cerberus logs this authorization with: timestamp, requested_by, task_description, scope, ttl.

### Step 2 — Token Delivery

The token is passed to the temp agent via environment variable only:
```
CERBERUS_TEMP_TOKEN=cbk_tmp_abc123...
```

It is never written to disk, config files, or logs. If it appears in a log,
Cerberus revokes it immediately as compromised.

### Step 3 — Vault Write (via Concierge)

When the temp agent has data to store, it calls Concierge — not Cerberus directly:

```
POST http://localhost:5004/vault/accept
{
  "token": "cbk_tmp_abc123...",
  "service": "SERVICE_NAME",
  "data": {
    "username": "...",
    "password": "...",
    "notes": "..."
  }
}
```

Concierge validates the token with Cerberus before writing anything:
```
POST http://localhost:8200/temp-agent/validate
{ "token": "cbk_tmp_abc123...", "action": "write", "vault_key": "SERVICE_NAME" }
```

Cerberus checks: token exists, not expired, action in scope, vault_key in whitelist.

Only after Cerberus confirms does Concierge write to the vault.

### Step 4 — Completion and Revocation

Temp agent signals done:
```
POST http://localhost:8200/temp-agent/complete
{ "token": "cbk_tmp_abc123...", "agent_id": "temp-scraper-001" }
```

Cerberus:
1. Revokes the token immediately (before this response returns)
2. Logs completion: timestamp, vault keys written, task outcome
3. Starts 10-minute deregistration timer for the agent_id

### Step 5 — Cleanup Audit

10 minutes after completion signal, Cerberus checks the registry:
- If `temp-scraper-001` is still registered → Cerberus sends deregister command and logs a warning
- If already gone → log confirmation, close the audit record

If a temp agent misses its TTL (token expires with no completion signal):
1. Cerberus revokes the token automatically at expiry
2. Logs: "Temp agent {id} token expired without completion — possible crash or hang"
3. Notifies Darnie if the task was flagged as important

---

## What Temp Agents May NOT Do

- Call vault endpoints directly — all vault writes go through Concierge
- Request tokens for themselves — only permanent agents or Darnie may request
- Extend their own TTL — only Darnie may approve an extension via Cerberus
- Store data outside the whitelisted vault keys in their token
- Spawn other agents
- Register as a permanent agent

---

## Vault Key Naming for Temp Agent Writes

Temp agents write to standard vault entries using the same naming convention:
```
{SERVICE}_{KEY_TYPE}
```

If the temp agent is registering a brand-new service for the first time, the
requesting agent must declare the new key name in the `vault_keys` whitelist
at authorization time. Cerberus will not permit writes to undeclared keys.

---

## Audit Trail

Every temp agent operation is logged in Cerberus's audit log:

| Field | Value |
|-------|-------|
| `event` | `temp_agent_authorized` / `temp_agent_vault_write` / `temp_agent_complete` / `temp_agent_expired` |
| `agent_id` | temp agent ID |
| `requested_by` | who authorized the spawn |
| `task_description` | human-readable task |
| `vault_keys_written` | list of keys actually written |
| `token_issued_at` | timestamp |
| `token_revoked_at` | timestamp |
| `outcome` | `completed` / `expired` / `error` |

This log is permanent. Temp agents don't get to clean up after themselves.

---

## When Concierge Is the Temp Agent

Concierge sometimes acts as a temporary operator for a single account registration
task — spinning up a browser session, completing registration, storing the result.
In this case, Concierge does not need a temp token. Concierge has standing write
access to the vault and is always audited by Cerberus.

The temp agent protocol applies only to agents that are not permanent members of
the Computer Black grid.
