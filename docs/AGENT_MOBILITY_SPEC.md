# Agent Mobility Spec
## "Move where the work is, answer wherever you are"

---

## The Problem

Agents currently have a fixed home. An agent on plugfoe uses plugfoe's CPU for
inference — slow for heavy tasks. The Mac (plugwan) has a full model library and
faster hardware, but agents don't live there.

The goal: agents move to plugwan when they have real work to do, run it fast and
free, then return to plugfoe when idle. If you message during a task, you get a
response from wherever the agent is — you never know or care which plug she's on.

---

## The Core Requirement: Externalized Mind State

**This is the prerequisite for everything else.**

Right now an agent's mind state (conversation history, task queue, memory) lives
in SQLite on the host it's running on. If the agent moves, that state stays behind.

Mind state must live somewhere both plugs can reach — not on either plug.

### Where it lives

**PlugOps (Cloud Run)** — already always-on, already trusted, already has a
`mind_state` module stub. This is the right place.

- Agent pushes a state snapshot to PlugOps before migrating
- Agent pulls state snapshot from PlugOps when booting on a new host
- Conversation history and task queue travel with the agent

### What gets externalized

```
MindStateSnapshot {
    agent_id:       str
    version:        int          # increments on every save
    timestamp:      float
    session_history: list[dict]  # last N conversation turns
    task_queue:     list[dict]   # pending + in-progress tasks
    working_memory: dict         # key facts the agent is holding mid-task
    host:           str          # where snapshot was taken (plugfoe/plugwan)
}
```

Local SQLite stays for fast per-turn reads during a session. It's a cache.
PlugOps mind_state is the source of truth for migration.

---

## Migration Protocol

### Trigger conditions (agent decides to move)

Move to plugwan when ALL of:
- Agent has a task in queue tagged `compute: heavy`
- plugwan Ollama is reachable (`http://100.113.209.66:11434`)
- No active user conversation in the last 5 minutes
- Agent is currently on plugfoe (not already on plugwan)

Return to plugfoe when ANY of:
- Task queue is empty
- plugwan goes unreachable
- Agent has been on plugwan for more than 4 hours with no active task

### Migration steps (plugfoe → plugwan)

```
1. LOCK    Set migration lock on Operator (5 min TTL)
           POST /api/v1/agents/{id}/migration/lock

2. SNAPSHOT Push full mind state to PlugOps mind_state server
           POST /api/v1/mind_state/{id}/snapshot

3. SIGNAL  Write a "migrate to plugwan" trigger file on plugwan
           (via SSH over Tailscale, or a plugwan-side watcher)

4. BOOT    plugwan starts the agent process
           Agent loads snapshot from PlugOps on boot
           Agent re-registers with Operator (409 = migration lock active, retry)

5. CONFIRM Operator sees new registration from plugwan IP
           Updates agent entry, clears migration lock
           Old plugfoe instance gets SIGTERM from watchdog

6. RESUME  Agent picks up task queue from loaded snapshot
           Continues work using plugwan Ollama
```

### During migration window (~30 seconds)

- Operator holds migration lock — no duplicate registration allowed
- Incoming messages queued in SSE inbox (already works — PlugOps buffers)
- After new instance registers, queued messages drain normally

---

## Boot sequence changes

When an agent boots, before starting loops:

```python
# 1. Try to restore from PlugOps mind_state
snapshot = mods.mind_state.pull_snapshot(agent_id)
if snapshot:
    restore_session_history(snapshot)
    restore_task_queue(snapshot)
    restore_working_memory(snapshot)
    logger.info(f"[boot] Restored from snapshot v{snapshot['version']}")
else:
    logger.info("[boot] No snapshot — fresh start")

# 2. Register with Operator (handles migration lock retry)
await bridge.connect()

# 3. Resume tasks if any in queue
if task_queue:
    logger.info(f"[boot] Resuming {len(task_queue)} tasks from snapshot")
```

---

## Operator changes

### New endpoints

```
POST /api/v1/agents/{id}/migration/lock
    Sets a migration lock for the agent (5 min TTL)
    Returns: {locked: true, expires_at: timestamp}

DELETE /api/v1/agents/{id}/migration/lock
    Clears lock early (called after successful new registration)

GET /api/v1/agents/{id}/migration/lock
    Returns current lock status
```

### Registration behavior with migration lock

When an agent registers and a migration lock is active:
- Accept the registration (it's the intended new instance)
- Clear the migration lock
- Mark old instance as migrated (not dead — different from crash)

---

## PlugOps mind_state server changes

### New endpoints

```
POST /api/v1/mind_state/{agent_id}/snapshot
    Store a full state snapshot
    Body: MindStateSnapshot
    Returns: {version: int, stored_at: timestamp}

GET /api/v1/mind_state/{agent_id}/snapshot
    Retrieve latest snapshot
    Returns: MindStateSnapshot or 404

GET /api/v1/mind_state/{agent_id}/snapshot/{version}
    Retrieve specific version (for rollback)
```

Storage: Firestore (Cloud Run native) or in-memory with periodic flush.
Keep last 5 versions per agent.

---

## Trigger mechanism: how plugfoe signals plugwan to boot

Two options:

**Option A — SSH trigger (simple)**
plugfoe SSHes to plugwan over Tailscale and runs:
```bash
ssh plugwan "systemctl start researcher"
```
Requires: plugfoe has an SSH key trusted by plugwan.

**Option B — Plugwan-side watcher (cleaner)**
plugwan runs a lightweight watcher process that polls PlugOps for
migration requests. When it sees one for a local agent, it starts
the systemd service. No SSH needed.

**Recommendation: Option B.** SSH from agent to host feels wrong.
A watcher on plugwan that owns its own process lifecycle is cleaner
and doesn't require cross-host SSH keys.

---

## plugwan watcher (new process)

```
plugwan-watcher.py
  - Polls GET /api/v1/agents/migration/pending?host=plugwan every 30s
  - For each pending migration: systemctl start {agent_id}
  - On agent exit: reports back to Operator
  - Managed by launchd on plugwan
```

---

## Build order

1. **PlugOps mind_state endpoints** — POST/GET snapshot (Firestore or in-memory)
2. **BlackZero boot sequence** — pull snapshot on boot, restore state
3. **BlackZero migration trigger** — detect heavy task + plugwan available → initiate
4. **Operator migration lock endpoints** — lock/unlock/status
5. **plugwan watcher** — lightweight process that starts agents on migration signal
6. **Return migration** — agent moves back to plugfoe when task done

Start with 1 + 2 — externalized mind state alone is valuable even without
full migration. An agent that crashes and restarts picks up where it left off.
That's Agent Hospital with zero extra infrastructure.

---

## What this unlocks

- **Agent Hospital** — crash on plugfoe, restart on plugfoe, state restored
- **Mobility** — move to plugwan for heavy work, return when done
- **Resilience** — plugfoe goes down, agents boot on plugwan automatically
- **Future: RunPod** — same protocol, different destination. Operator spins up
  RunPod pod, watcher on pod pulls snapshot, agent runs on GPU, returns when done.

---

*Spec written 2026-05-06*
