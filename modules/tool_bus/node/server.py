"""
tool_bus node — tool registration and execution routing.

Agents don't run tools internally — they request them through the bus.
The bus routes to whichever provider registered the tool.
The Operator is the default executor for most tools (web_search, shell, etc.).
Engineer0 is only called for hard technical tasks.

Execution model:
  Sync  — bus POSTs to provider exec_url, waits for HTTP response (≤ timeout)
  Async — bus queues the job, provider POSTs result back when done

Provider registration:
  Any agent may register tools it provides, along with an exec_url.
  Multiple providers can register the same tool (fallback chain).
  Providers are ranked by priority (lower = preferred).

Job lifecycle:
  pending → running → done | failed | timed_out

HTTP API (port 9105):
  POST   /tools/register          register tools (one agent, list of tools)
  DELETE /tools/provider/{id}     deregister all tools for an agent
  GET    /tools                   list all registered tools + providers
  GET    /tools/{tool_name}       info on a specific tool
  POST   /execute                 execute a tool (sync or async)
  GET    /jobs/{job_id}           get job status + result
  POST   /jobs/{job_id}/result    provider posts result back (async mode)
  GET    /jobs                    recent job log
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

PORT         = 9105
COMM_URL     = "http://127.0.0.1:9100"
DEFAULT_TIMEOUT = 30.0   # seconds for sync execution
MAX_JOBS_KEEP   = 5_000  # max jobs retained in log

app = FastAPI(title="ToolBus Node", version="1.0")


# ── DB ────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(
        Path(__file__).parent / "tool_bus.db"
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


from pathlib import Path


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS providers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name       TEXT NOT NULL,
                agent_id        TEXT NOT NULL,
                description     TEXT NOT NULL DEFAULT '',
                input_schema    TEXT NOT NULL DEFAULT '{}',
                exec_url        TEXT NOT NULL,
                priority        INTEGER NOT NULL DEFAULT 50,
                registered_at   REAL NOT NULL,
                UNIQUE(tool_name, agent_id)
            );

            CREATE INDEX IF NOT EXISTS idx_providers_tool
                ON providers(tool_name, priority);

            CREATE TABLE IF NOT EXISTS jobs (
                job_id          TEXT PRIMARY KEY,
                tool_name       TEXT NOT NULL,
                from_agent      TEXT NOT NULL,
                provider_id     TEXT NOT NULL,
                input_data      TEXT NOT NULL DEFAULT '{}',
                status          TEXT NOT NULL DEFAULT 'pending',
                result          TEXT,
                error           TEXT,
                exec_mode       TEXT NOT NULL DEFAULT 'sync',
                created_at      REAL NOT NULL,
                started_at      REAL,
                completed_at    REAL,
                timeout_sec     REAL NOT NULL DEFAULT 30
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_from_agent
                ON jobs(from_agent, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_status
                ON jobs(status, created_at DESC);
        """)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _broadcast(event: str, payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{COMM_URL}/send", json={
                "from": "tool_bus",
                "to":   "tool-events",
                "payload": {"event": event, **payload},
            })
    except Exception:
        pass


def _pick_provider(tool_name: str) -> Optional[sqlite3.Row]:
    """Return the highest-priority (lowest priority number) provider for a tool."""
    with db() as conn:
        return conn.execute(
            "SELECT * FROM providers WHERE tool_name=? ORDER BY priority LIMIT 1",
            (tool_name,)
        ).fetchone()


async def _call_provider(exec_url: str, payload: dict, timeout: float) -> dict:
    """POST to provider's exec_url, return parsed response."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(exec_url, json=payload)
        r.raise_for_status()
        return r.json()


# ── Request / Response models ─────────────────────────────────────────────────

class ToolSpec(BaseModel):
    name:         str
    description:  str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    priority:     int = 50


class RegisterRequest(BaseModel):
    agent_id: str
    exec_url: str   # base URL — bus will POST to exec_url with {"tool_name", "input", "job_id"}
    tools:    list[ToolSpec]


class ExecuteRequest(BaseModel):
    from_agent: str
    tool_name:  str
    input:      dict[str, Any] = Field(default_factory=dict)
    timeout:    float = DEFAULT_TIMEOUT
    mode:       str   = "sync"   # sync | async


class JobResultRequest(BaseModel):
    result: Any  = None
    error:  str  = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/tools/register", status_code=201)
async def register_tools(req: RegisterRequest):
    """Provider agent registers its tools."""
    now = time.time()
    registered = []
    with db() as conn:
        for tool in req.tools:
            conn.execute("""
                INSERT INTO providers
                  (tool_name, agent_id, description, input_schema, exec_url,
                   priority, registered_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(tool_name, agent_id) DO UPDATE SET
                  description=excluded.description,
                  input_schema=excluded.input_schema,
                  exec_url=excluded.exec_url,
                  priority=excluded.priority,
                  registered_at=excluded.registered_at
            """, (
                tool.name, req.agent_id, tool.description,
                json.dumps(tool.input_schema), req.exec_url,
                tool.priority, now,
            ))
            registered.append(tool.name)

    asyncio.create_task(_broadcast("tools_registered", {
        "agent_id": req.agent_id, "tools": registered
    }))
    return {"ok": True, "agent_id": req.agent_id, "registered": registered}


@app.delete("/tools/provider/{agent_id}")
async def deregister_provider(agent_id: str):
    """Remove all tools registered by a provider agent."""
    with db() as conn:
        result = conn.execute(
            "SELECT COUNT(*) as n FROM providers WHERE agent_id=?", (agent_id,)
        ).fetchone()["n"]
        conn.execute("DELETE FROM providers WHERE agent_id=?", (agent_id,))
    return {"ok": True, "agent_id": agent_id, "removed": result}


@app.get("/tools")
async def list_tools():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM providers ORDER BY tool_name, priority"
        ).fetchall()

    # Group by tool_name
    tools: dict[str, dict] = {}
    for r in rows:
        name = r["tool_name"]
        if name not in tools:
            tools[name] = {"tool_name": name, "providers": []}
        tools[name]["providers"].append({
            "agent_id":    r["agent_id"],
            "description": r["description"],
            "exec_url":    r["exec_url"],
            "priority":    r["priority"],
        })

    return {"ok": True, "count": len(tools), "tools": list(tools.values())}


@app.get("/tools/{tool_name}")
async def get_tool(tool_name: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM providers WHERE tool_name=? ORDER BY priority",
            (tool_name,)
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "tool_not_found"})
    return {
        "ok":        True,
        "tool_name": tool_name,
        "providers": [
            {
                "agent_id":    r["agent_id"],
                "description": r["description"],
                "exec_url":    r["exec_url"],
                "priority":    r["priority"],
            }
            for r in rows
        ]
    }


@app.post("/execute")
async def execute_tool(req: ExecuteRequest):
    """Route a tool execution request to the appropriate provider."""
    provider = _pick_provider(req.tool_name)
    if not provider:
        raise HTTPException(status_code=404, detail={
            "error": "no_provider",
            "tool_name": req.tool_name,
            "message": f"No provider registered for tool '{req.tool_name}'",
        })

    job_id = str(uuid.uuid4())
    now    = time.time()

    with db() as conn:
        conn.execute("""
            INSERT INTO jobs
              (job_id, tool_name, from_agent, provider_id, input_data,
               status, exec_mode, created_at, timeout_sec)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            job_id, req.tool_name, req.from_agent,
            provider["agent_id"], json.dumps(req.input),
            "pending", req.mode, now, req.timeout,
        ))

    if req.mode == "async":
        # Fire and forget — provider must POST result back
        asyncio.create_task(_run_async(job_id, provider, req))
        return {
            "ok":      True,
            "job_id":  job_id,
            "status":  "pending",
            "mode":    "async",
        }

    # Sync — wait for provider response
    return await _run_sync(job_id, provider, req)


async def _run_sync(job_id: str, provider: sqlite3.Row, req: ExecuteRequest) -> dict:
    """Execute synchronously — block until provider responds or timeout."""
    now = time.time()
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE job_id=?",
            (now, job_id)
        )

    try:
        payload = {
            "job_id":    job_id,
            "tool_name": req.tool_name,
            "input":     req.input,
            "from_agent": req.from_agent,
        }
        data = await _call_provider(provider["exec_url"], payload, req.timeout)

        result  = data.get("result")
        error   = data.get("error", "")
        status  = "failed" if error else "done"
        done_at = time.time()

        with db() as conn:
            conn.execute("""
                UPDATE jobs SET status=?, result=?, error=?, completed_at=?
                WHERE job_id=?
            """, (status, json.dumps(result), error, done_at, job_id))
            _prune_jobs(conn)

        asyncio.create_task(_broadcast("tool_executed", {
            "job_id": job_id, "tool_name": req.tool_name,
            "from_agent": req.from_agent, "status": status,
            "latency_ms": round((done_at - now) * 1000, 1),
        }))

        return {
            "ok":       True,
            "job_id":   job_id,
            "status":   status,
            "tool_name": req.tool_name,
            "result":   result,
            "error":    error,
            "latency_ms": round((time.time() - now) * 1000, 1),
        }

    except httpx.TimeoutException:
        with db() as conn:
            conn.execute(
                "UPDATE jobs SET status='timed_out', completed_at=? WHERE job_id=?",
                (time.time(), job_id)
            )
        raise HTTPException(status_code=504, detail={
            "error": "provider_timeout",
            "job_id": job_id,
            "tool_name": req.tool_name,
        })

    except Exception as e:
        with db() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, completed_at=? WHERE job_id=?",
                (str(e), time.time(), job_id)
            )
        raise HTTPException(status_code=502, detail={
            "error": "provider_error",
            "job_id": job_id,
            "message": str(e),
        })


async def _run_async(job_id: str, provider: sqlite3.Row, req: ExecuteRequest) -> None:
    """Fire-and-forget: call provider, it will POST result back via /jobs/{job_id}/result."""
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE job_id=?",
            (time.time(), job_id)
        )
    try:
        payload = {
            "job_id":     job_id,
            "tool_name":  req.tool_name,
            "input":      req.input,
            "from_agent": req.from_agent,
            "callback":   f"http://127.0.0.1:{PORT}/jobs/{job_id}/result",
        }
        await _call_provider(provider["exec_url"], payload, req.timeout)
    except Exception as e:
        with db() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, completed_at=? WHERE job_id=?",
                (str(e), time.time(), job_id)
            )


@app.post("/jobs/{job_id}/result")
async def post_job_result(job_id: str, req: JobResultRequest):
    """Provider posts result back for async jobs."""
    with db() as conn:
        row = conn.execute("SELECT job_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "job_not_found"})
        status = "failed" if req.error else "done"
        conn.execute("""
            UPDATE jobs SET status=?, result=?, error=?, completed_at=?
            WHERE job_id=?
        """, (status, json.dumps(req.result), req.error, time.time(), job_id))
    return {"ok": True, "job_id": job_id, "status": status}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})
    result = json.loads(row["result"]) if row["result"] else None
    return {
        "ok":          True,
        "job_id":      row["job_id"],
        "tool_name":   row["tool_name"],
        "from_agent":  row["from_agent"],
        "provider_id": row["provider_id"],
        "status":      row["status"],
        "result":      result,
        "error":       row["error"],
        "exec_mode":   row["exec_mode"],
        "created_at":  row["created_at"],
        "started_at":  row["started_at"],
        "completed_at": row["completed_at"],
    }


@app.get("/jobs")
async def list_jobs(limit: int = 50, from_agent: str = "", status: str = ""):
    with db() as conn:
        if from_agent and status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE from_agent=? AND status=? ORDER BY created_at DESC LIMIT ?",
                (from_agent, status, limit)
            ).fetchall()
        elif from_agent:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE from_agent=? ORDER BY created_at DESC LIMIT ?",
                (from_agent, limit)
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "jobs": [
            {
                "job_id":     r["job_id"],
                "tool_name":  r["tool_name"],
                "from_agent": r["from_agent"],
                "status":     r["status"],
                "exec_mode":  r["exec_mode"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@app.get("/health")
async def health():
    with db() as conn:
        tools    = conn.execute("SELECT COUNT(DISTINCT tool_name) as n FROM providers").fetchone()["n"]
        providers = conn.execute("SELECT COUNT(*) as n FROM providers").fetchone()["n"]
        pending  = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='pending'").fetchone()["n"]
        running  = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='running'").fetchone()["n"]
    return {
        "ok":               True,
        "registered_tools": tools,
        "providers":        providers,
        "pending_jobs":     pending,
        "running_jobs":     running,
        "port":             PORT,
    }


@app.get("/stats")
async def stats():
    with db() as conn:
        total     = conn.execute("SELECT COUNT(*) as n FROM jobs").fetchone()["n"]
        done      = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='done'").fetchone()["n"]
        failed    = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='failed'").fetchone()["n"]
        timed_out = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='timed_out'").fetchone()["n"]
        tools     = conn.execute("SELECT COUNT(DISTINCT tool_name) as n FROM providers").fetchone()["n"]
        providers = conn.execute("SELECT COUNT(DISTINCT agent_id) as n FROM providers").fetchone()["n"]
    return {
        "ok":         True,
        "total_jobs": total,
        "done":       done,
        "failed":     failed,
        "timed_out":  timed_out,
        "registered_tools":    tools,
        "registered_providers": providers,
    }


def _prune_jobs(conn: sqlite3.Connection) -> None:
    conn.execute("""
        DELETE FROM jobs WHERE job_id NOT IN (
            SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT ?
        )
    """, (MAX_JOBS_KEEP,))


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
