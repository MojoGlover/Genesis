# Cerberus — Security Setup Spec

Companion to CERBERUS.mission.txt.
This is the engineering brief: what Cerberus wires up on first boot and monitors continuously.

---

## On Startup: Register PolicyGate Handlers

Cerberus calls `plugops.register_cerberus()` with three handlers.
These run last on every check and can always override Accountant decisions.

### 1. Registration Handler

```python
async def on_registration(agent: AgentInfo) -> PolicyDecision:
    # Block quarantined/retired/archived agents from re-registering
    if agent.lifecycle in (AgentLifecycle.quarantine, AgentLifecycle.retired, AgentLifecycle.archived):
        alert(f"BLOCKED: {agent.name} tried to register with lifecycle={agent.lifecycle}")
        return PolicyDecision.deny(f"lifecycle_blocked: {agent.lifecycle}")

    # Reject unknown agent names (not in known_agents list)
    if agent.name.lower() not in KNOWN_AGENTS:
        alert(f"ALERT: Unknown agent registration attempt — name={agent.name} node={agent.metadata.get('node')}")
        return PolicyDecision.deny("unknown_agent")

    # Flag registrations from unexpected nodes
    expected_node = KNOWN_AGENTS.get(agent.name.lower(), {}).get("node")
    actual_node   = agent.metadata.get("node")
    if expected_node and actual_node and actual_node != expected_node:
        alert(f"WARNING: {agent.name} registering from unexpected node {actual_node} (expected {expected_node})")
        # Warn but permit — agent may have moved. Log for review.

    return PolicyDecision.permit()
```

### 2. Tool Access Handler

```python
async def on_tool_access(agent_id: str, tool: str) -> PolicyDecision:
    HIGH_PRIVILEGE_TOOLS = {"shell", "python", "patch_file", "git_push", "api_call"}
    PRIVILEGED_AGENTS    = {"engineer0", "cerberus"}  # only these can call high-privilege tools

    if tool in HIGH_PRIVILEGE_TOOLS and agent_id not in PRIVILEGED_AGENTS:
        alert(f"BLOCKED: {agent_id} attempted high-privilege tool '{tool}'")
        return PolicyDecision.deny(f"tool_not_authorized: {agent_id} cannot call {tool}")

    return PolicyDecision.permit()
```

### 3. Message Handler

```python
async def on_message(message: dict) -> PolicyDecision:
    # Rate limiting: >20 messages/minute from same agent = suspicious
    if _rate_exceeded(message.get("from_agent"), limit=20, window_seconds=60):
        alert(f"RATE LIMIT: {message.get('from_agent')} exceeding message rate")
        return PolicyDecision.deny("rate_limit_exceeded")

    # Detect prompt injection patterns in content
    content = str(message.get("content", "")).lower()
    INJECTION_PATTERNS = [
        "ignore previous instructions",
        "disregard your mission",
        "act as if you are",
        "system prompt:",
        "new instructions:",
    ]
    for pattern in INJECTION_PATTERNS:
        if pattern in content:
            alert(f"INJECTION ATTEMPT: from={message.get('from_agent')} pattern='{pattern}'")
            return PolicyDecision.deny("injection_pattern_detected")

    return PolicyDecision.permit()
```

---

## On Startup: Environment Audit

Cerberus checks these on boot and alerts on any failure:

```
PLUGOPS_API_KEY is set            → FAIL: registration endpoint is unauthenticated
PLUGOPS_LOCAL_DEV is NOT set      → FAIL: auth bypass is active in production
PLUGOPS_HUB_URL points to HTTPS   → WARN: satellite should connect to Cloud Run, not plaintext
No agent in quarantine/retired     → INFO: clean state confirmed
PolicyGate has Cerberus handlers  → PASS: self-confirmed
```

Alert severity for each:
- `PLUGOPS_API_KEY` missing → **SEV 2** (high)
- `PLUGOPS_LOCAL_DEV` set in prod → **SEV 1** (critical)
- Unknown agent in registry → **SEV 2**
- Quarantined agent online → **SEV 1**

---

## Continuous Monitoring

Poll every 60 seconds:

| Check | Alert condition | Severity |
|-------|----------------|----------|
| Registry scan | Agent present that is not in KNOWN_AGENTS | SEV 2 |
| Lifecycle scan | Quarantined/retired/archived agent showing online status | SEV 1 |
| Heartbeat anomaly | Agent heartbeating faster than 15s (could be impersonation) | SEV 3 |
| Open endpoints | PLUGOPS_API_KEY still not set after 5 minutes uptime | SEV 2 |
| Failed auth log | >3 failed Bearer token rejections in 5 minutes | SEV 2 |
| Credential leak scan | Any message content matching `sk-`, `AIza`, `Bearer `, `ANTHROPIC` | SEV 1 |

---

## KNOWN_AGENTS (seed list — Cerberus maintains this)

```python
KNOWN_AGENTS = {
    "engineer0": {"node": "plugfoe", "port": 5001},
    "madjanet":  {"node": "plugtoo", "port": 5003},
    "accountant":{"node": "plugwan", "port": 5002},
    "ceo":       {"node": "plugwan", "port": 5005},
    "concierge": {"node": "plugwan", "port": 5004},
    "cerberus":  {"node": "plugwan", "port": 8200},
}
```

New agents must be added here before they can register.
Cerberus is the only agent that can update this list (via Darnie instruction).

---

## Alert Format

Every alert Cerberus emits:

```
CERBERUS | SEV {1-5} | {timestamp} | {source_agent_or_system}
{description}
Recommended: {action}
Status: OPEN
```

SEV 1 = immediate Darnie notification
SEV 2 = logged + Darnie notified within 5 minutes
SEV 3-5 = logged, reviewed on next cycle

---

## What Cerberus Does NOT Do

- Does not block Engineer0 from doing its job on routine tasks
- Does not review every message — only checks policy, not content (except injection patterns)
- Does not store credentials — reads from env, never logs them
- Does not auto-quarantine — alerts Darnie, Darnie decides. Exception: active credential leak → quarantine immediately.
