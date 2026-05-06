"""
scheduler node — cron-style and one-shot task scheduling for agents.

Agents register jobs with a schedule (cron expression or delay in seconds).
The scheduler fires POST callbacks to the agent's registered endpoint at the right time.
All executions are logged with status and latency.

Job types:
  cron    — runs on a cron schedule (standard 5-field: min hour dom mon dow)
  once    — fires once after a delay in seconds
  interval — fires every N seconds

HTTP API (port 9107):
  POST   /jobs                   create a new scheduled job
  DELETE /jobs/{job_id}          cancel a job
  GET    /jobs                   list all jobs (with next_fire time)
  GET    /jobs/{job_id}          single job detail
  POST   /jobs/{job_id}/pause    pause a job (skip fires until resumed)
  POST   /jobs/{job_id}/resume   resume a paused job
  POST   /jobs/{job_id}/fire     manually trigger a job immediately
  GET    /history                recent execution history
  GET    /history/{job_id}       execution history for a specific job
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

PORT          = 9107
COMM_URL      = "http://127.0.0.1:9100"
DB_PATH       = Path(__file__).parent / "scheduler.db"
FIRE_TIMEOUT  = 10.0     # seconds to wait for callback response
HISTORY_KEEP  = 10_000   # max execution history entries
TICK_INTERVAL = 1.0      # scheduler tick every second

app = FastAPI(title="Scheduler Node", version="1.0")

# In-memory next_fire cache (rebuilt on startup from DB)
_next_fire: dict[str, float] = {}
_scheduler_task: Optional[asyncio.Task] = None


# ── DB ────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id          TEXT PRIMARY KEY,
                name            TEXT NOT NULL DEFAULT '',
                agent_id        TEXT NOT NULL,
                callback_url    TEXT NOT NULL,
                job_type        TEXT NOT NULL DEFAULT 'cron',
                schedule        TEXT NOT NULL,
                payload         TEXT NOT NULL DEFAULT '{}',
                status          TEXT NOT NULL DEFAULT 'active',
                last_fire       REAL,
                next_fire       REAL,
                fire_count      INTEGER NOT NULL DEFAULT 0,
                created_at      REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_next_fire
                ON jobs(status, next_fire);
            CREATE INDEX IF NOT EXISTS idx_jobs_agent
                ON jobs(agent_id);

            CREATE TABLE IF NOT EXISTS history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT NOT NULL,
                agent_id        TEXT NOT NULL,
                fired_at        REAL NOT NULL,
                status_code     INTEGER,
                latency_ms      REAL,
                error           TEXT NOT NULL DEFAULT '',
                result          TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_history_job
                ON history(job_id, fired_at DESC);
        """)


# ── Cron / schedule math ──────────────────────────────────────────────────────

def _next_cron_fire(cron: str, after: float) -> float:
    """
    Minimal cron parser — 5-field standard cron.
    Returns the next fire timestamp after `after`.
    Only supports numeric values and * (no step/range syntax beyond basic needs).
    """
    fields = cron.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression: {cron!r}")

    minute_f, hour_f, dom_f, month_f, dow_f = fields

    def match(field: str, value: int) -> bool:
        if field == "*":
            return True
        parts = field.split(",")
        for p in parts:
            if "/" in p:
                base, step = p.split("/")
                base_val = 0 if base == "*" else int(base)
                if (value - base_val) % int(step) == 0:
                    return True
            elif "-" in p:
                lo, hi = p.split("-")
                if int(lo) <= value <= int(hi):
                    return True
            elif p == str(value):
                return True
        return False

    # Scan forward minute-by-minute (max 1 year = 525600 minutes)
    t = int(after) + 60  # at least 1 minute in the future
    t = (t // 60) * 60   # align to minute boundary

    for _ in range(525600):
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        if (match(month_f, dt.month) and
                match(dom_f, dt.day) and
                match(dow_f, dt.weekday()) and
                match(hour_f, dt.hour) and
                match(minute_f, dt.minute)):
            return float(t)
        t += 60

    raise ValueError(f"No valid fire time found for cron: {cron!r}")


def _compute_next_fire(job: sqlite3.Row, after: Optional[float] = None) -> Optional[float]:
    """Compute the next fire time for a job."""
    now = after or time.time()
    jtype = job["job_type"]

    if jtype == "cron":
        return _next_cron_fire(job["schedule"], now)

    elif jtype == "interval":
        interval = float(job["schedule"])
        last = job["last_fire"] or job["created_at"]
        # Next = last + interval, but at least now+1s
        nxt = last + interval
        while nxt <= now:
            nxt += interval
        return nxt

    elif jtype == "once":
        if job["fire_count"] > 0:
            return None  # already fired — done
        delay = float(job["schedule"])
        return job["created_at"] + delay

    return None


# ── Scheduler loop ────────────────────────────────────────────────────────────

async def _scheduler_loop() -> None:
    """Main tick loop — checks for due jobs every TICK_INTERVAL seconds."""
    while True:
        await asyncio.sleep(TICK_INTERVAL)
        now = time.time()

        with db() as conn:
            due = conn.execute(
                "SELECT * FROM jobs WHERE status='active' AND next_fire<=?", (now,)
            ).fetchall()

        for job in due:
            asyncio.create_task(_fire_job(job))


async def _fire_job(job: sqlite3.Row) -> None:
    """Fire one job — POST callback, record history, compute next fire."""
    fired_at = time.time()
    payload  = json.loads(job["payload"])
    payload["job_id"]   = job["job_id"]
    payload["fired_at"] = fired_at

    status_code = None
    error       = ""
    result      = ""
    latency_ms  = 0.0

    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=FIRE_TIMEOUT) as client:
            r = await client.post(job["callback_url"], json=payload)
        latency_ms  = (time.perf_counter() - t0) * 1000
        status_code = r.status_code
        result      = r.text[:500]
    except Exception as e:
        error = str(e)[:200]

    with db() as conn:
        # Record history
        conn.execute("""
            INSERT INTO history (job_id, agent_id, fired_at, status_code, latency_ms, error, result)
            VALUES (?,?,?,?,?,?,?)
        """, (job["job_id"], job["agent_id"], fired_at,
              status_code, latency_ms, error, result))

        # Compute next fire
        updated_job = conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job["job_id"],)
        ).fetchone()

        if updated_job and updated_job["status"] == "active":
            # Update fire count + last_fire
            conn.execute(
                "UPDATE jobs SET fire_count=fire_count+1, last_fire=? WHERE job_id=?",
                (fired_at, job["job_id"])
            )
            # Re-fetch to get updated row for next_fire computation
            updated = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()
            nxt = _compute_next_fire(updated)
            if nxt:
                conn.execute("UPDATE jobs SET next_fire=? WHERE job_id=?", (nxt, job["job_id"]))
            else:
                # once job — mark done
                conn.execute("UPDATE jobs SET status='done', next_fire=NULL WHERE job_id=?",
                             (job["job_id"],))

        # Prune history
        conn.execute("""
            DELETE FROM history WHERE id NOT IN (
                SELECT id FROM history ORDER BY id DESC LIMIT ?
            )
        """, (HISTORY_KEEP,))


# ── Request / Response models ─────────────────────────────────────────────────

class JobRequest(BaseModel):
    name:         str = ""
    agent_id:     str
    callback_url: str
    job_type:     str = "cron"      # cron | interval | once
    schedule:     str               # cron string | seconds as string
    payload:      dict[str, Any] = Field(default_factory=dict)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/jobs", status_code=201)
async def create_job(req: JobRequest):
    """Create a new scheduled job."""
    import uuid as _uuid
    job_id = str(_uuid.uuid4())
    now    = time.time()

    # Validate schedule and compute first fire
    try:
        mock_row = {
            "job_type": req.job_type,
            "schedule": req.schedule,
            "created_at": now,
            "last_fire": None,
            "fire_count": 0,
        }
        # Use sqlite3.Row-like dict access via a namespace
        class _Row(dict):
            def __getitem__(self, k):
                return super().__getitem__(k)
        next_fire = _compute_next_fire(_Row(mock_row), after=now)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"error": "invalid_schedule", "message": str(e)})

    with db() as conn:
        conn.execute("""
            INSERT INTO jobs
              (job_id, name, agent_id, callback_url, job_type, schedule,
               payload, status, next_fire, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            job_id, req.name, req.agent_id, req.callback_url,
            req.job_type, req.schedule,
            json.dumps(req.payload), "active", next_fire, now,
        ))

    return {
        "ok":       True,
        "job_id":   job_id,
        "next_fire": next_fire,
        "status":   "active",
    }


@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT job_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        conn.execute("UPDATE jobs SET status='cancelled', next_fire=NULL WHERE job_id=?", (job_id,))
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


@app.get("/jobs")
async def list_jobs(agent_id: str = "", status: str = ""):
    with db() as conn:
        if agent_id and status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE agent_id=? AND status=? ORDER BY next_fire",
                (agent_id, status)
            ).fetchall()
        elif agent_id:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE agent_id=? ORDER BY next_fire", (agent_id,)
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY next_fire", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY next_fire LIMIT 200"
            ).fetchall()

    return {
        "ok":    True,
        "count": len(rows),
        "jobs": [
            {
                "job_id":       r["job_id"],
                "name":         r["name"],
                "agent_id":     r["agent_id"],
                "job_type":     r["job_type"],
                "schedule":     r["schedule"],
                "status":       r["status"],
                "fire_count":   r["fire_count"],
                "next_fire":    r["next_fire"],
                "last_fire":    r["last_fire"],
            }
            for r in rows
        ]
    }


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {
        "ok":           True,
        "job_id":       row["job_id"],
        "name":         row["name"],
        "agent_id":     row["agent_id"],
        "callback_url": row["callback_url"],
        "job_type":     row["job_type"],
        "schedule":     row["schedule"],
        "payload":      json.loads(row["payload"]),
        "status":       row["status"],
        "fire_count":   row["fire_count"],
        "next_fire":    row["next_fire"],
        "last_fire":    row["last_fire"],
        "created_at":   row["created_at"],
    }


@app.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        if row["status"] != "active":
            raise HTTPException(status_code=409, detail={"error": f"cannot_pause_{row['status']}"})
        conn.execute("UPDATE jobs SET status='paused' WHERE job_id=?", (job_id,))
    return {"ok": True, "job_id": job_id, "status": "paused"}


@app.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        if row["status"] != "paused":
            raise HTTPException(status_code=409, detail={"error": f"cannot_resume_{row['status']}"})
        nxt = _compute_next_fire(row)
        conn.execute(
            "UPDATE jobs SET status='active', next_fire=? WHERE job_id=?",
            (nxt, job_id)
        )
    return {"ok": True, "job_id": job_id, "status": "active", "next_fire": nxt}


@app.post("/jobs/{job_id}/fire")
async def manual_fire(job_id: str):
    """Manually trigger a job immediately, regardless of schedule."""
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    asyncio.create_task(_fire_job(row))
    return {"ok": True, "job_id": job_id, "message": "Fired manually."}


@app.get("/history")
async def list_history(limit: int = 50):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM history ORDER BY fired_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "history": [
            {
                "id":          r["id"],
                "job_id":      r["job_id"],
                "agent_id":    r["agent_id"],
                "fired_at":    r["fired_at"],
                "status_code": r["status_code"],
                "latency_ms":  r["latency_ms"],
                "error":       r["error"],
            }
            for r in rows
        ]
    }


@app.get("/history/{job_id}")
async def job_history(job_id: str, limit: int = 20):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM history WHERE job_id=? ORDER BY fired_at DESC LIMIT ?",
            (job_id, limit)
        ).fetchall()
    return {
        "ok":     True,
        "job_id": job_id,
        "count":  len(rows),
        "history": [dict(r) for r in rows],
    }


@app.get("/health")
async def health():
    with db() as conn:
        active    = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='active'").fetchone()["n"]
        total     = conn.execute("SELECT COUNT(*) as n FROM jobs").fetchone()["n"]
        fired_24h = conn.execute(
            "SELECT COUNT(*) as n FROM history WHERE fired_at>=?", (time.time() - 86400,)
        ).fetchone()["n"]
    return {
        "ok":          True,
        "active_jobs": active,
        "total_jobs":  total,
        "fires_24h":   fired_24h,
        "port":        PORT,
    }


@app.get("/stats")
async def stats():
    with db() as conn:
        by_status = conn.execute(
            "SELECT status, COUNT(*) as n FROM jobs GROUP BY status"
        ).fetchall()
        total_fires = conn.execute("SELECT COUNT(*) as n FROM history").fetchone()["n"]
        success     = conn.execute(
            "SELECT COUNT(*) as n FROM history WHERE status_code>=200 AND status_code<300"
        ).fetchone()["n"]
        errors      = conn.execute(
            "SELECT COUNT(*) as n FROM history WHERE error!='' OR status_code>=400"
        ).fetchone()["n"]
    return {
        "ok":           True,
        "jobs_by_status": {r["status"]: r["n"] for r in by_status},
        "total_fires":  total_fires,
        "successful_fires": success,
        "error_fires":  errors,
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    # Recompute next_fire for all active jobs (handles restarts)
    with db() as conn:
        rows = conn.execute("SELECT * FROM jobs WHERE status='active'").fetchall()
        for row in rows:
            try:
                nxt = _compute_next_fire(row)
                if nxt:
                    conn.execute("UPDATE jobs SET next_fire=? WHERE job_id=?",
                                 (nxt, row["job_id"]))
            except Exception:
                pass

    global _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
