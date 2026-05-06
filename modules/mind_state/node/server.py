"""
mind_state node — externalized per-agent state storage.

Fits into the stack:
  - Keyed by agent_id from the registry module (same namespace).
  - Survives agent crashes — state persists across restarts.
  - Agent Hospital reads last known state to rebuild a dead agent.
  - Registry's agent_died event is the trigger: state stays, agent is gone.
  - Versioned: every save creates a new version. Checkpoints are kept longer.
  - Comm module broadcasts state change events so supervisor can react.

What gets stored per agent:
  - memory:          recent message/conversation history
  - active_task:     what the agent was doing when it saved
  - beliefs:         current knowledge/working assumptions
  - context_summary: compressed context (for long-running sessions)
  - goals:           current goal stack
  - tools_in_use:    which tools were active
  - custom:          agent-specific fields (anything)

HTTP API (port 9102):
  POST   /agents/{id}/state            save state (auto-versions)
  GET    /agents/{id}/state            get latest state
  GET    /agents/{id}/state/history    list all versions (metadata only)
  GET    /agents/{id}/state/{version}  get a specific version
  POST   /agents/{id}/state/checkpoint explicitly mark latest as a checkpoint
  DELETE /agents/{id}/state            wipe all state for agent
  GET    /agents                       list all agents with saved state
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

PORT            = 9102
COMM_URL        = "http://127.0.0.1:9100"
REGISTRY_URL    = "http://127.0.0.1:9101"
DB_PATH         = Path(__file__).parent / "mind_state.db"

MAX_VERSIONS    = 20      # regular versions to keep per agent
CHECKPOINT_KEEP = 50      # checkpoint versions to keep per agent
MAX_STATE_MB    = 50      # reject states larger than this
COMPRESS_ABOVE  = 4096    # bytes — compress states larger than this

app = FastAPI(title="MindState Node", version="1.0")


# ── DB ────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS states (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id        TEXT NOT NULL,
                version         INTEGER NOT NULL,
                snapshot_type   TEXT NOT NULL DEFAULT 'auto',
                state_data      BLOB NOT NULL,
                compressed      INTEGER NOT NULL DEFAULT 0,
                size_bytes      INTEGER NOT NULL DEFAULT 0,
                label           TEXT NOT NULL DEFAULT '',
                saved_at        REAL NOT NULL,
                UNIQUE(agent_id, version)
            );

            CREATE INDEX IF NOT EXISTS idx_agent_version
                ON states(agent_id, version DESC);

            CREATE TABLE IF NOT EXISTS agent_meta (
                agent_id        TEXT PRIMARY KEY,
                latest_version  INTEGER NOT NULL DEFAULT 0,
                total_saves     INTEGER NOT NULL DEFAULT 0,
                first_save      REAL NOT NULL,
                last_save       REAL NOT NULL
            );
        """)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compress(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=6)


def _decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


def _encode_state(state: dict) -> tuple[bytes, bool]:
    """Encode state dict to bytes, compressing if large."""
    raw = json.dumps(state, ensure_ascii=False).encode("utf-8")
    if len(raw) > COMPRESS_ABOVE:
        return _compress(raw), True
    return raw, False


def _decode_state(data: bytes, compressed: bool) -> dict:
    raw = _decompress(data) if compressed else data
    return json.loads(raw.decode("utf-8"))


def _next_version(conn: sqlite3.Connection, agent_id: str) -> int:
    meta = conn.execute(
        "SELECT latest_version FROM agent_meta WHERE agent_id=?", (agent_id,)
    ).fetchone()
    return (meta["latest_version"] + 1) if meta else 1


def _prune_old_versions(conn: sqlite3.Connection, agent_id: str) -> None:
    """Keep MAX_VERSIONS regular + CHECKPOINT_KEEP checkpoint versions."""
    # Prune regular (non-checkpoint) versions beyond MAX_VERSIONS
    conn.execute("""
        DELETE FROM states
        WHERE agent_id=? AND snapshot_type != 'checkpoint'
          AND id NOT IN (
              SELECT id FROM states
              WHERE agent_id=? AND snapshot_type != 'checkpoint'
              ORDER BY version DESC
              LIMIT ?
          )
    """, (agent_id, agent_id, MAX_VERSIONS))

    # Prune checkpoint versions beyond CHECKPOINT_KEEP
    conn.execute("""
        DELETE FROM states
        WHERE agent_id=? AND snapshot_type = 'checkpoint'
          AND id NOT IN (
              SELECT id FROM states
              WHERE agent_id=? AND snapshot_type = 'checkpoint'
              ORDER BY version DESC
              LIMIT ?
          )
    """, (agent_id, agent_id, CHECKPOINT_KEEP))


async def _broadcast(event_type: str, agent_id: str, payload: dict) -> None:
    """Non-blocking broadcast to comm module."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{COMM_URL}/send", json={
                "from":    "mind_state",
                "to":      "mind_state-events",
                "payload": {"event": event_type, "agent_id": agent_id, **payload},
            })
    except Exception:
        pass


# ── Request / Response models ─────────────────────────────────────────────────

class SaveStateRequest(BaseModel):
    state:          dict[str, Any]
    snapshot_type:  str = "auto"    # auto | checkpoint | shutdown | crash_recovery
    label:          str = ""        # optional human note e.g. "before_deploy_task"


class StateRecord(BaseModel):
    agent_id:      str
    version:       int
    snapshot_type: str
    label:         str
    size_bytes:    int
    saved_at:      float
    state:         Optional[dict] = None   # None in history listings


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/agents/{agent_id}/state", status_code=201)
async def save_state(agent_id: str, req: SaveStateRequest):
    now = time.time()

    raw_size = len(json.dumps(req.state).encode("utf-8"))
    if raw_size > MAX_STATE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"State too large: {raw_size // 1024}KB > {MAX_STATE_MB}MB limit"
        )

    data, compressed = _encode_state(req.state)

    with db() as conn:
        version = _next_version(conn, agent_id)

        conn.execute(
            """INSERT INTO states
               (agent_id, version, snapshot_type, state_data, compressed,
                size_bytes, label, saved_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (agent_id, version, req.snapshot_type, data,
             int(compressed), raw_size, req.label, now)
        )

        # Upsert agent_meta
        conn.execute("""
            INSERT INTO agent_meta (agent_id, latest_version, total_saves, first_save, last_save)
            VALUES (?,?,1,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
                latest_version = excluded.latest_version,
                total_saves    = total_saves + 1,
                last_save      = excluded.last_save
        """, (agent_id, version, now, now))

        _prune_old_versions(conn, agent_id)

    asyncio.create_task(_broadcast("state_saved", agent_id, {
        "version":       version,
        "snapshot_type": req.snapshot_type,
        "size_bytes":    raw_size,
        "label":         req.label,
    }))

    return {
        "ok":            True,
        "agent_id":      agent_id,
        "version":       version,
        "snapshot_type": req.snapshot_type,
        "size_bytes":    raw_size,
        "compressed":    compressed,
    }


@app.get("/agents/{agent_id}/state")
async def get_latest_state(agent_id: str):
    with db() as conn:
        row = conn.execute(
            """SELECT * FROM states WHERE agent_id=?
               ORDER BY version DESC LIMIT 1""",
            (agent_id,)
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_state", "agent_id": agent_id,
                    "message": "No state saved for this agent."}
        )

    state = _decode_state(row["state_data"], bool(row["compressed"]))
    return {
        "ok":            True,
        "agent_id":      agent_id,
        "version":       row["version"],
        "snapshot_type": row["snapshot_type"],
        "label":         row["label"],
        "size_bytes":    row["size_bytes"],
        "saved_at":      row["saved_at"],
        "state":         state,
    }


@app.get("/agents/{agent_id}/state/history")
async def get_history(agent_id: str, limit: int = 20):
    with db() as conn:
        rows = conn.execute(
            """SELECT id, version, snapshot_type, label, size_bytes, saved_at
               FROM states WHERE agent_id=?
               ORDER BY version DESC LIMIT ?""",
            (agent_id, limit)
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail={"error": "no_state"})

    return {
        "ok":      True,
        "agent_id": agent_id,
        "count":   len(rows),
        "history": [
            {
                "version":       r["version"],
                "snapshot_type": r["snapshot_type"],
                "label":         r["label"],
                "size_bytes":    r["size_bytes"],
                "saved_at":      r["saved_at"],
            }
            for r in rows
        ]
    }


@app.get("/agents/{agent_id}/state/{version}")
async def get_version(agent_id: str, version: int):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM states WHERE agent_id=? AND version=?",
            (agent_id, version)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail={"error": "version_not_found"})

    state = _decode_state(row["state_data"], bool(row["compressed"]))
    return {
        "ok":            True,
        "agent_id":      agent_id,
        "version":       row["version"],
        "snapshot_type": row["snapshot_type"],
        "label":         row["label"],
        "size_bytes":    row["size_bytes"],
        "saved_at":      row["saved_at"],
        "state":         state,
    }


@app.post("/agents/{agent_id}/state/checkpoint")
async def mark_checkpoint(agent_id: str, label: str = ""):
    """Promote the latest version to checkpoint so it survives longer pruning."""
    with db() as conn:
        row = conn.execute(
            "SELECT version FROM states WHERE agent_id=? ORDER BY version DESC LIMIT 1",
            (agent_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "no_state"})

        version = row["version"]
        conn.execute(
            "UPDATE states SET snapshot_type='checkpoint', label=? WHERE agent_id=? AND version=?",
            (label or f"checkpoint-v{version}", agent_id, version)
        )

    return {
        "ok":      True,
        "agent_id": agent_id,
        "version": version,
        "snapshot_type": "checkpoint",
        "message": f"Version {version} marked as checkpoint.",
    }


@app.delete("/agents/{agent_id}/state")
async def wipe_state(agent_id: str):
    """Wipe all state for an agent. Irreversible. Used by Agent Hospital after rebuild."""
    with db() as conn:
        conn.execute("DELETE FROM states WHERE agent_id=?", (agent_id,))
        conn.execute("DELETE FROM agent_meta WHERE agent_id=?", (agent_id,))

    asyncio.create_task(_broadcast("state_wiped", agent_id, {}))
    return {"ok": True, "agent_id": agent_id, "message": "All state wiped."}


@app.get("/agents")
async def list_agents_with_state():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_meta ORDER BY last_save DESC"
        ).fetchall()

    return {
        "ok":    True,
        "count": len(rows),
        "agents": [
            {
                "agent_id":       r["agent_id"],
                "latest_version": r["latest_version"],
                "total_saves":    r["total_saves"],
                "first_save":     r["first_save"],
                "last_save":      r["last_save"],
            }
            for r in rows
        ]
    }


@app.get("/health")
async def health():
    with db() as conn:
        agents = conn.execute("SELECT COUNT(*) as n FROM agent_meta").fetchone()["n"]
        versions = conn.execute("SELECT COUNT(*) as n FROM states").fetchone()["n"]
    return {"ok": True, "agents": agents, "total_versions": versions, "port": PORT}


@app.get("/stats")
async def stats():
    with db() as conn:
        agents     = conn.execute("SELECT COUNT(*) as n FROM agent_meta").fetchone()["n"]
        versions   = conn.execute("SELECT COUNT(*) as n FROM states").fetchone()["n"]
        total_kb   = conn.execute("SELECT SUM(size_bytes)/1024 as kb FROM states").fetchone()["kb"] or 0
        compressed = conn.execute(
            "SELECT COUNT(*) as n FROM states WHERE compressed=1"
        ).fetchone()["n"]
        checkpoints = conn.execute(
            "SELECT COUNT(*) as n FROM states WHERE snapshot_type='checkpoint'"
        ).fetchone()["n"]

    return {
        "ok":              True,
        "agents":          agents,
        "total_versions":  versions,
        "checkpoints":     checkpoints,
        "compressed":      compressed,
        "total_size_kb":   round(total_kb, 1),
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
