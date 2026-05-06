"""
Registry node — agent identity, liveness, single-instance enforcement.

Fits into the stack:
  - Uses comm module (port 9100) to broadcast agent join/leave events
    so supervisor and other listeners react in real time.
  - Agent records are keyed by agent_id — mind_state uses these same
    keys to store per-agent state externally.
  - Supervisor polls /agents or subscribes via comm to watch for deaths.

HTTP API (port 9101):
  POST   /register                 register an agent (409 if already live)
  DELETE /agents/{id}              deregister
  POST   /agents/{id}/heartbeat    keep-alive (404 → agent must re-register)
  POST   /agents/{id}/migrate      acquire migration lock (allows re-register during handoff)
  GET    /agents                   list all live agents
  GET    /agents/{id}              single agent record
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

PORT             = 9101
COMM_URL         = "http://127.0.0.1:9100"   # communication module
DB_PATH          = Path(__file__).parent / "registry.db"
HEARTBEAT_TTL    = 90    # seconds — 3 missed beats at 30s interval = dead
MIGRATION_TTL    = 300   # 5 min migration lock
SWEEP_INTERVAL   = 30    # how often we check for dead agents

app = FastAPI(title="Registry Node", version="1.0")

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
                role            TEXT NOT NULL DEFAULT '',
                capabilities    TEXT NOT NULL DEFAULT '[]',
                host            TEXT NOT NULL DEFAULT 'localhost',
                port            INTEGER,
                session_id      TEXT NOT NULL,
                metadata        TEXT NOT NULL DEFAULT '{}',
                registered_at   REAL NOT NULL,
                last_heartbeat  REAL NOT NULL,
                status          TEXT NOT NULL DEFAULT 'live'
            );

            CREATE TABLE IF NOT EXISTS migration_locks (
                agent_id    TEXT PRIMARY KEY,
                locked_at   REAL NOT NULL,
                expires_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type  TEXT NOT NULL,
                agent_id    TEXT NOT NULL,
                payload     TEXT NOT NULL,
                ts          REAL NOT NULL
            );
        """)


# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    agent_id:     str
    name:         str
    role:         str = ""
    capabilities: list[str] = Field(default_factory=list)
    host:         str = "localhost"
    port:         Optional[int] = None
    metadata:     dict = Field(default_factory=dict)


class HeartbeatResponse(BaseModel):
    ok:         bool
    agent_id:   str
    status:     str
    next_by:    float   # unix timestamp — miss this and you're dead


class AgentRecord(BaseModel):
    model_config = {"from_attributes": True}

    agent_id:       str
    name:           str
    role:           str
    capabilities:   list[str]
    host:           str
    port:           Optional[int]
    session_id:     str
    metadata:       dict
    registered_at:  float
    last_heartbeat: float
    status:         str


def _row_to_record(row) -> AgentRecord:
    return AgentRecord(
        agent_id       = row["agent_id"],
        name           = row["name"],
        role           = row["role"],
        capabilities   = json.loads(row["capabilities"]),
        host           = row["host"],
        port           = row["port"],
        session_id     = row["session_id"],
        metadata       = json.loads(row["metadata"]),
        registered_at  = row["registered_at"],
        last_heartbeat = row["last_heartbeat"],
        status         = row["status"],
    )


# ── Comm broadcast (non-blocking, best-effort) ────────────────────────────────

async def _broadcast(event_type: str, agent_id: str, payload: dict) -> None:
    """
    Broadcast a registry event via the communication module.
    Agents (supervisor, dashboard, etc.) subscribe to 'registry' inbox.
    Fire-and-forget — registry never blocks on comm availability.
    """
    msg = {"event": event_type, "agent_id": agent_id, **payload}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{COMM_URL}/send", json={
                "from":    "registry",
                "to":      "registry-events",   # well-known channel name
                "payload": msg,
            })
    except Exception:
        pass  # comm being down never breaks the registry

    # Also store in local events table for replay
    with db() as conn:
        conn.execute(
            "INSERT INTO events (event_type, agent_id, payload, ts) VALUES (?,?,?,?)",
            (event_type, agent_id, json.dumps(payload), time.time()),
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/register", status_code=201)
async def register(req: RegisterRequest):
    now = time.time()
    session_id = str(uuid.uuid4())

    with db() as conn:
        # Check migration lock — allows re-register during controlled handoff
        lock = conn.execute(
            "SELECT expires_at FROM migration_locks WHERE agent_id=?",
            (req.agent_id,)
        ).fetchone()
        has_lock = lock and lock["expires_at"] > now

        # Check if already live
        existing = conn.execute(
            "SELECT agent_id, status FROM agents WHERE agent_id=? AND status='live'",
            (req.agent_id,)
        ).fetchone()

        if existing and not has_lock:
            raise HTTPException(
                status_code=409,
                detail={
                    "error":    "already_registered",
                    "agent_id": req.agent_id,
                    "message":  (
                        f"Agent '{req.agent_id}' is already live. "
                        "Deregister first or use /migrate to acquire a handoff lock."
                    ),
                }
            )

        # Clear any stale record and migration lock
        conn.execute("DELETE FROM agents WHERE agent_id=?", (req.agent_id,))
        conn.execute("DELETE FROM migration_locks WHERE agent_id=?", (req.agent_id,))

        conn.execute(
            """INSERT INTO agents
               (agent_id, name, role, capabilities, host, port,
                session_id, metadata, registered_at, last_heartbeat, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                req.agent_id,
                req.name,
                req.role,
                json.dumps(req.capabilities),
                req.host,
                req.port,
                session_id,
                json.dumps(req.metadata),
                now, now, "live",
            )
        )

    asyncio.create_task(_broadcast("agent_joined", req.agent_id, {
        "name": req.name, "role": req.role,
        "capabilities": req.capabilities, "session_id": session_id,
    }))

    return {
        "ok":        True,
        "agent_id":  req.agent_id,
        "session_id": session_id,
        "heartbeat_interval": 30,
        "heartbeat_ttl":      HEARTBEAT_TTL,
    }


@app.post("/agents/{agent_id}/heartbeat")
async def heartbeat(agent_id: str):
    now = time.time()
    with db() as conn:
        row = conn.execute(
            "SELECT status FROM agents WHERE agent_id=? AND status='live'",
            (agent_id,)
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail={
                    "error":   "not_registered",
                    "agent_id": agent_id,
                    "message": "Agent not found or not live. Re-register.",
                }
            )
        conn.execute(
            "UPDATE agents SET last_heartbeat=? WHERE agent_id=?",
            (now, agent_id)
        )

    return HeartbeatResponse(
        ok       = True,
        agent_id = agent_id,
        status   = "live",
        next_by  = now + HEARTBEAT_TTL,
    )


@app.delete("/agents/{agent_id}", status_code=200)
async def deregister(agent_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT agent_id FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        conn.execute(
            "UPDATE agents SET status='deregistered' WHERE agent_id=?",
            (agent_id,)
        )

    asyncio.create_task(_broadcast("agent_left", agent_id, {"reason": "deregistered"}))
    return {"ok": True, "agent_id": agent_id, "status": "deregistered"}


@app.post("/agents/{agent_id}/migrate")
async def acquire_migration_lock(agent_id: str):
    """
    Acquire a migration lock before shutting down old instance.
    Allows a new instance to register without 409 for MIGRATION_TTL seconds.
    """
    now = time.time()
    expires = now + MIGRATION_TTL
    with db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO migration_locks (agent_id, locked_at, expires_at)
               VALUES (?,?,?)""",
            (agent_id, now, expires)
        )
    return {
        "ok":        True,
        "agent_id":  agent_id,
        "expires_at": expires,
        "ttl_seconds": MIGRATION_TTL,
        "message":   "Migration lock acquired. New instance may register within 5 minutes.",
    }


@app.get("/agents")
async def list_agents(role: str = "", capability: str = ""):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM agents WHERE status='live' ORDER BY registered_at"
        ).fetchall()

    agents = [_row_to_record(r) for r in rows]

    # Filter by role or capability if requested
    if role:
        agents = [a for a in agents if a.role == role]
    if capability:
        agents = [a for a in agents if capability in a.capabilities]

    return {"ok": True, "count": len(agents), "agents": [a.model_dump() for a in agents]}


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _row_to_record(row).model_dump()


@app.get("/events")
async def get_events(limit: int = 50):
    """Recent registry events — supervisor and dashboard subscribe to these."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "ok": True,
        "events": [
            {
                "id":         r["id"],
                "event_type": r["event_type"],
                "agent_id":   r["agent_id"],
                "payload":    json.loads(r["payload"]),
                "ts":         r["ts"],
            }
            for r in rows
        ]
    }


@app.get("/health")
async def health():
    with db() as conn:
        live = conn.execute(
            "SELECT COUNT(*) as n FROM agents WHERE status='live'"
        ).fetchone()["n"]
    return {"ok": True, "live_agents": live, "port": PORT}


@app.get("/stats")
async def stats():
    with db() as conn:
        counts = conn.execute(
            "SELECT status, COUNT(*) as n FROM agents GROUP BY status"
        ).fetchall()
        events = conn.execute("SELECT COUNT(*) as n FROM events").fetchone()["n"]
    return {
        "ok":     True,
        "agents": {r["status"]: r["n"] for r in counts},
        "events": events,
    }


# ── Background sweeper ────────────────────────────────────────────────────────

async def _liveness_sweeper():
    """Mark agents dead if they haven't heartbeated within HEARTBEAT_TTL."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL)
        now = time.time()
        cutoff = now - HEARTBEAT_TTL
        with db() as conn:
            dead = conn.execute(
                "SELECT agent_id, name FROM agents WHERE status='live' AND last_heartbeat < ?",
                (cutoff,)
            ).fetchall()
            if dead:
                ids = [r["agent_id"] for r in dead]
                conn.execute(
                    f"UPDATE agents SET status='dead' WHERE agent_id IN ({','.join('?'*len(ids))})",
                    ids
                )

        for row in dead:
            asyncio.create_task(_broadcast("agent_died", row["agent_id"], {
                "name":   row["name"],
                "reason": "heartbeat_timeout",
                "cutoff": cutoff,
            }))

        # Also expire stale migration locks
        with db() as conn:
            conn.execute("DELETE FROM migration_locks WHERE expires_at < ?", (now,))


@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(_liveness_sweeper())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
