"""
Supervisor node — agent process lifecycle management.

Fits into the stack:
  - Subscribes to comm module (SSE) for registry events (agent_died, agent_left).
  - On unexpected death: reads mind_state → restarts process → verifies re-registration.
  - Replaces nohup &, launchd one-offs, and manual restart scripts.
  - Agents declare themselves to the supervisor at boot via POST /agents/{id}/declare.
  - Supervisor tracks PIDs, restart counts, backoff, and crash history.

Restart policies:
  always      — restart on any exit (zero or non-zero)
  on_failure  — restart only if exit code != 0
  never       — no auto-restart (manual only)

Process states:
  stopped   — not running, never started or cleanly stopped
  starting  — process launched, waiting for registry confirmation
  running   — confirmed live in registry, heartbeating
  stopping  — SIGTERM sent, waiting for exit
  crashed   — exited unexpectedly, backoff before restart
  healing   — Agent Hospital in progress (mind_state restore + restart)
  failed    — max restarts exceeded, giving up

HTTP API (port 9103):
  POST   /agents/{id}/declare    declare an agent to supervisor (config + command)
  POST   /agents/{id}/start      start a declared agent
  POST   /agents/{id}/stop       stop (SIGTERM → SIGKILL after timeout)
  POST   /agents/{id}/restart    stop + start
  POST   /agents/{id}/heal       manually trigger Agent Hospital
  DELETE /agents/{id}            remove agent from supervisor catalog
  GET    /agents                 list all managed agents
  GET    /agents/{id}            single agent status
  GET    /events                 recent supervisor events
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

PORT           = 9103
COMM_URL       = "http://127.0.0.1:9100"
REGISTRY_URL   = "http://127.0.0.1:9101"
MIND_STATE_URL = "http://127.0.0.1:9102"
DB_PATH        = Path(__file__).parent / "supervisor.db"

START_TIMEOUT  = 30    # seconds to wait for agent to appear in registry after start
STOP_TIMEOUT   = 10    # seconds before SIGKILL after SIGTERM
MAX_RESTARTS   = 5     # default max before marking failed
BACKOFF_BASE   = 2     # exponential backoff base (seconds)
BACKOFF_MAX    = 120   # cap backoff at 2 minutes
POLL_INTERVAL  = 15    # seconds between registry liveness polls

app = FastAPI(title="Supervisor Node", version="1.0")

# In-memory process table — PIDs don't survive restarts anyway
_processes: dict[str, subprocess.Popen] = {}


# ── DB ────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id        TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                command         TEXT NOT NULL,      -- JSON list
                working_dir     TEXT NOT NULL,
                env_extra       TEXT NOT NULL DEFAULT '{}',
                restart_policy  TEXT NOT NULL DEFAULT 'on_failure',
                max_restarts    INTEGER NOT NULL DEFAULT 5,
                backoff_base    INTEGER NOT NULL DEFAULT 2,
                state           TEXT NOT NULL DEFAULT 'stopped',
                pid             INTEGER,
                restart_count   INTEGER NOT NULL DEFAULT 0,
                last_start      REAL,
                last_stop       REAL,
                last_crash      REAL,
                declared_at     REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                detail      TEXT NOT NULL DEFAULT '',
                ts          REAL NOT NULL
            );
        """)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_event(conn: sqlite3.Connection, agent_id: str, event_type: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (agent_id, event_type, detail, ts) VALUES (?,?,?,?)",
        (agent_id, event_type, detail, time.time())
    )


def _set_state(conn: sqlite3.Connection, agent_id: str, state: str, **kwargs) -> None:
    sets = ["state=?"]
    vals = [state]
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append(agent_id)
    conn.execute(f"UPDATE agents SET {', '.join(sets)} WHERE agent_id=?", vals)


def _backoff(restart_count: int, base: int) -> float:
    delay = base ** restart_count
    return min(delay, BACKOFF_MAX)


async def _broadcast(event_type: str, agent_id: str, detail: str = "") -> None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{COMM_URL}/send", json={
                "from": "supervisor",
                "to":   "supervisor-events",
                "payload": {"event": event_type, "agent_id": agent_id, "detail": detail},
            })
    except Exception:
        pass


async def _registry_is_live(agent_id: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{REGISTRY_URL}/agents/{agent_id}")
            if r.status_code == 200:
                return r.json().get("status") == "live"
    except Exception:
        pass
    return False


async def _restore_mind_state(agent_id: str) -> Optional[dict]:
    """Read the last known mind_state for an agent (for Agent Hospital)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{MIND_STATE_URL}/agents/{agent_id}/state")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


def _launch_process(agent_id: str, command: list, working_dir: str, env_extra: dict) -> Optional[subprocess.Popen]:
    """Launch agent process. Returns Popen or None on failure."""
    env = os.environ.copy()
    env.update(env_extra)
    try:
        proc = subprocess.Popen(
            command,
            cwd=os.path.expanduser(working_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,   # own process group — SIGTERM doesn't cascade
        )
        return proc
    except Exception as e:
        return None


# ── Start / stop logic ────────────────────────────────────────────────────────

async def _do_start(agent_id: str, is_heal: bool = False) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "not_declared"}

        state = row["state"]
        if state in ("running", "starting"):
            return {"ok": False, "error": f"already_{state}"}

        # Check max restarts (not enforced for manual starts or heals)
        if not is_heal and row["restart_count"] >= row["max_restarts"] and state == "crashed":
            return {"ok": False, "error": "max_restarts_exceeded",
                    "restart_count": row["restart_count"]}

        command   = json.loads(row["command"])
        wdir      = row["working_dir"]
        env_extra = json.loads(row["env_extra"])

        # If healing: pass mind_state path via env so agent can self-restore
        if is_heal:
            mind = await _restore_mind_state(agent_id)
            if mind:
                env_extra["MIND_STATE_RESTORE_VERSION"] = str(mind.get("version", ""))
                env_extra["MIND_STATE_URL"]             = MIND_STATE_URL

        proc = _launch_process(agent_id, command, wdir, env_extra)
        if not proc:
            _set_state(conn, agent_id, "crashed", last_crash=time.time())
            _log_event(conn, agent_id, "start_failed", "subprocess.Popen failed")
            return {"ok": False, "error": "launch_failed"}

        _processes[agent_id] = proc
        _set_state(conn, agent_id, "starting", pid=proc.pid,
                   last_start=time.time(),
                   restart_count=row["restart_count"] + (1 if row["last_start"] else 0))
        _log_event(conn, agent_id, "heal" if is_heal else "start", f"pid={proc.pid}")

    asyncio.create_task(_broadcast(
        "agent_healing" if is_heal else "agent_starting", agent_id, f"pid={proc.pid}"
    ))

    # Wait for registry confirmation in background
    asyncio.create_task(_await_registration(agent_id, proc.pid))

    return {"ok": True, "agent_id": agent_id, "pid": proc.pid,
            "state": "starting", "is_heal": is_heal}


async def _await_registration(agent_id: str, pid: int) -> None:
    """Poll registry until agent appears or timeout."""
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        await asyncio.sleep(2)
        if await _registry_is_live(agent_id):
            with db() as conn:
                _set_state(conn, agent_id, "running")
                _log_event(conn, agent_id, "running", "confirmed live in registry")
            await _broadcast("agent_running", agent_id)
            return

        # Check if process already died
        proc = _processes.get(agent_id)
        if proc and proc.poll() is not None:
            with db() as conn:
                _set_state(conn, agent_id, "crashed", last_crash=time.time(), pid=None)
                _log_event(conn, agent_id, "crashed", f"exited before registry (code={proc.poll()})")
            await _broadcast("agent_crashed", agent_id, f"exit_code={proc.poll()}")
            asyncio.create_task(_handle_crash(agent_id))
            return

    # Timeout
    with db() as conn:
        _set_state(conn, agent_id, "crashed", last_crash=time.time())
        _log_event(conn, agent_id, "start_timeout", f"did not appear in registry within {START_TIMEOUT}s")
    await _broadcast("agent_start_timeout", agent_id)


async def _do_stop(agent_id: str) -> dict:
    proc = _processes.get(agent_id)
    with db() as conn:
        row = conn.execute("SELECT pid, state FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "not_declared"}
        pid = row["pid"]
        _set_state(conn, agent_id, "stopping", last_stop=time.time())
        _log_event(conn, agent_id, "stop", f"pid={pid}")

    # SIGTERM first
    if proc:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass

        # Wait for clean exit
        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, proc.wait),
                timeout=STOP_TIMEOUT
            )
        except asyncio.TimeoutError:
            # SIGKILL
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    _processes.pop(agent_id, None)
    with db() as conn:
        _set_state(conn, agent_id, "stopped", pid=None)
        _log_event(conn, agent_id, "stopped")

    await _broadcast("agent_stopped", agent_id)
    return {"ok": True, "agent_id": agent_id, "state": "stopped"}


async def _handle_crash(agent_id: str) -> None:
    """Apply restart policy after a crash."""
    with db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not row:
            return

        policy        = row["restart_policy"]
        restart_count = row["restart_count"]
        max_r         = row["max_restarts"]
        backoff_b     = row["backoff_base"]

    if policy == "never":
        return

    if restart_count >= max_r:
        with db() as conn:
            _set_state(conn, agent_id, "failed")
            _log_event(conn, agent_id, "failed", f"max_restarts={max_r} exceeded")
        await _broadcast("agent_failed", agent_id, f"max_restarts={max_r}")
        return

    delay = _backoff(restart_count, backoff_b)
    await _broadcast("agent_backoff", agent_id, f"delay={delay:.0f}s restart={restart_count+1}/{max_r}")
    await asyncio.sleep(delay)

    # Heal — restore mind_state then restart
    await _do_start(agent_id, is_heal=True)


# ── Registry event listener ───────────────────────────────────────────────────

async def _listen_registry_events() -> None:
    """
    Subscribe to comm module SSE for registry events.
    React to agent_died by triggering heal if we manage that agent.
    """
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", f"{COMM_URL}/inbox/supervisor", timeout=None
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            msg = json.loads(line[5:].strip())
                            payload = msg.get("payload", {})
                            event   = payload.get("event", "")
                            agent_id = payload.get("agent_id", "")

                            if not agent_id:
                                continue

                            if event == "agent_died":
                                await _on_agent_died(agent_id)
                            elif event == "agent_left":
                                await _on_agent_left(agent_id)
                        except Exception:
                            continue
        except Exception:
            # Comm not available — retry after delay
            await asyncio.sleep(5)


async def _on_agent_died(agent_id: str) -> None:
    """Registry says agent died (missed heartbeats). Trigger heal if we manage it."""
    with db() as conn:
        row = conn.execute(
            "SELECT state, restart_policy FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if not row:
            return   # not our agent
        if row["state"] in ("stopping", "stopped", "failed"):
            return   # expected stop — ignore

        _set_state(conn, agent_id, "crashed", last_crash=time.time(), pid=None)
        _log_event(conn, agent_id, "registry_death", "missed heartbeats — healing")

    _processes.pop(agent_id, None)
    await _broadcast("agent_healing_triggered", agent_id, "registry reported death")
    asyncio.create_task(_handle_crash(agent_id))


async def _on_agent_left(agent_id: str) -> None:
    """Agent cleanly deregistered. Mark stopped (don't restart)."""
    with db() as conn:
        row = conn.execute("SELECT state FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not row:
            return
        if row["state"] not in ("stopping",):
            _set_state(conn, agent_id, "stopped", last_stop=time.time(), pid=None)
            _log_event(conn, agent_id, "clean_exit", "deregistered cleanly")


# ── Liveness poller ───────────────────────────────────────────────────────────

async def _liveness_poller() -> None:
    """
    Periodically check running agents against registry.
    Catches crashes that don't emit events (e.g. killed -9).
    """
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        with db() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM agents WHERE state='running'"
            ).fetchall()

        for row in rows:
            agent_id = row["agent_id"]
            if not await _registry_is_live(agent_id):
                # Check if process actually exited
                proc = _processes.get(agent_id)
                if proc and proc.poll() is not None:
                    with db() as conn:
                        _set_state(conn, agent_id, "crashed",
                                   last_crash=time.time(), pid=None)
                        _log_event(conn, agent_id, "poller_crash",
                                   f"process exited (code={proc.poll()}), not in registry")
                    _processes.pop(agent_id, None)
                    asyncio.create_task(_handle_crash(agent_id))


# ── Endpoints ─────────────────────────────────────────────────────────────────

class DeclareRequest(BaseModel):
    name:           str
    command:        list[str]
    working_dir:    str
    env_extra:      dict = Field(default_factory=dict)
    restart_policy: str  = "on_failure"   # always | on_failure | never
    max_restarts:   int  = MAX_RESTARTS
    backoff_base:   int  = BACKOFF_BASE


@app.post("/agents/{agent_id}/declare", status_code=201)
async def declare_agent(agent_id: str, req: DeclareRequest):
    now = time.time()
    with db() as conn:
        conn.execute("""
            INSERT INTO agents
              (agent_id, name, command, working_dir, env_extra,
               restart_policy, max_restarts, backoff_base, declared_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
              name=excluded.name, command=excluded.command,
              working_dir=excluded.working_dir, env_extra=excluded.env_extra,
              restart_policy=excluded.restart_policy,
              max_restarts=excluded.max_restarts, backoff_base=excluded.backoff_base
        """, (
            agent_id, req.name, json.dumps(req.command),
            req.working_dir, json.dumps(req.env_extra),
            req.restart_policy, req.max_restarts, req.backoff_base, now,
        ))
        _log_event(conn, agent_id, "declared", f"cmd={req.command[0]}")
    return {"ok": True, "agent_id": agent_id, "state": "stopped"}


@app.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    return await _do_start(agent_id)


@app.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    return await _do_stop(agent_id)


@app.post("/agents/{agent_id}/restart")
async def restart_agent(agent_id: str):
    await _do_stop(agent_id)
    await asyncio.sleep(1)
    return await _do_start(agent_id)


@app.post("/agents/{agent_id}/heal")
async def heal_agent(agent_id: str):
    """Manually trigger Agent Hospital — restore mind_state and restart."""
    with db() as conn:
        row = conn.execute("SELECT agent_id FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not_declared"})
        _set_state(conn, agent_id, "healing")
        _log_event(conn, agent_id, "manual_heal", "triggered by API")
    return await _do_start(agent_id, is_heal=True)


@app.delete("/agents/{agent_id}")
async def remove_agent(agent_id: str):
    await _do_stop(agent_id)
    with db() as conn:
        conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
        _log_event(conn, agent_id, "removed")
    return {"ok": True, "agent_id": agent_id}


@app.get("/agents")
async def list_agents():
    with db() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY declared_at").fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "agents": [
            {
                "agent_id":       r["agent_id"],
                "name":           r["name"],
                "state":          r["state"],
                "pid":            r["pid"],
                "restart_count":  r["restart_count"],
                "restart_policy": r["restart_policy"],
                "last_start":     r["last_start"],
                "last_crash":     r["last_crash"],
            }
            for r in rows
        ]
    }


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_declared"})
    return dict(row)


@app.get("/events")
async def get_events(limit: int = 50, agent_id: str = ""):
    with db() as conn:
        if agent_id:
            rows = conn.execute(
                "SELECT * FROM events WHERE agent_id=? ORDER BY ts DESC LIMIT ?",
                (agent_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
    return {
        "ok":    True,
        "events": [
            {"id": r["id"], "agent_id": r["agent_id"],
             "event_type": r["event_type"], "detail": r["detail"], "ts": r["ts"]}
            for r in rows
        ]
    }


@app.get("/health")
async def health():
    with db() as conn:
        counts = conn.execute(
            "SELECT state, COUNT(*) as n FROM agents GROUP BY state"
        ).fetchall()
    return {"ok": True, "states": {r["state"]: r["n"] for r in counts}, "port": PORT}


@app.get("/stats")
async def stats():
    with db() as conn:
        total    = conn.execute("SELECT COUNT(*) as n FROM agents").fetchone()["n"]
        running  = conn.execute("SELECT COUNT(*) as n FROM agents WHERE state='running'").fetchone()["n"]
        crashed  = conn.execute("SELECT COUNT(*) as n FROM agents WHERE state='crashed'").fetchone()["n"]
        failed   = conn.execute("SELECT COUNT(*) as n FROM agents WHERE state='failed'").fetchone()["n"]
        events   = conn.execute("SELECT COUNT(*) as n FROM events").fetchone()["n"]
        restarts = conn.execute("SELECT SUM(restart_count) as n FROM agents").fetchone()["n"] or 0
    return {
        "ok": True, "total": total, "running": running,
        "crashed": crashed, "failed": failed,
        "total_restarts": restarts, "total_events": events,
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(_listen_registry_events())
    asyncio.create_task(_liveness_poller())


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
