"""
ledger node — immutable cost and activity accounting for all agents.

Every agent reports what it spent (API calls, tokens, compute).
The Accountant reads this to produce financial truth.
No agent may modify a past entry — append-only, HMAC-signed rows.

What gets recorded per entry:
  agent_id     — who spent it
  resource     — what was consumed  (openai/gpt-4, anthropic/claude, ollama/llama3, shell, etc.)
  units        — how much           (tokens, seconds, requests)
  unit_type    — tokens | seconds | requests | bytes
  cost_usd     — dollar cost (0.0 for free resources)
  task_id      — optional task correlation
  session_id   — optional session grouping
  metadata     — arbitrary JSON

Signed with HMAC-SHA256 using a per-node secret so tampering is detectable.

HTTP API (port 9106):
  POST   /entries              record a cost entry (returns entry_id + hmac)
  GET    /entries              query entries (filter by agent, resource, date range)
  GET    /entries/{entry_id}   single entry with hmac verification
  GET    /summary/{agent_id}   total spend per resource for an agent
  GET    /summary              total spend per agent across entire system
  GET    /budget/{agent_id}    compare spend to configured budget
  POST   /budget/{agent_id}    set budget for an agent
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

PORT      = 9106
COMM_URL  = "http://127.0.0.1:9100"
DB_PATH   = Path(__file__).parent / "ledger.db"

# HMAC secret — loaded from env or generated once and stored
_HMAC_KEY: bytes = os.environ.get("LEDGER_HMAC_KEY", "cmptrblk-ledger-v1-secret").encode()

app = FastAPI(title="Ledger Node", version="1.0")


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
            CREATE TABLE IF NOT EXISTS entries (
                entry_id    TEXT PRIMARY KEY,
                agent_id    TEXT NOT NULL,
                resource    TEXT NOT NULL,
                units       REAL NOT NULL DEFAULT 0,
                unit_type   TEXT NOT NULL DEFAULT 'tokens',
                cost_usd    REAL NOT NULL DEFAULT 0.0,
                task_id     TEXT NOT NULL DEFAULT '',
                session_id  TEXT NOT NULL DEFAULT '',
                metadata    TEXT NOT NULL DEFAULT '{}',
                recorded_at REAL NOT NULL,
                hmac        TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_entries_agent
                ON entries(agent_id, recorded_at DESC);
            CREATE INDEX IF NOT EXISTS idx_entries_resource
                ON entries(resource, recorded_at DESC);
            CREATE INDEX IF NOT EXISTS idx_entries_date
                ON entries(recorded_at DESC);

            CREATE TABLE IF NOT EXISTS budgets (
                agent_id      TEXT PRIMARY KEY,
                daily_usd     REAL NOT NULL DEFAULT 0,
                monthly_usd   REAL NOT NULL DEFAULT 0,
                alert_pct     REAL NOT NULL DEFAULT 80.0,
                updated_at    REAL NOT NULL
            );
        """)


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _sign(entry_id: str, agent_id: str, resource: str,
          units: float, cost_usd: float, recorded_at: float) -> str:
    msg = f"{entry_id}|{agent_id}|{resource}|{units}|{cost_usd}|{recorded_at}"
    return hmac.new(_HMAC_KEY, msg.encode(), hashlib.sha256).hexdigest()


def _verify(row: sqlite3.Row) -> bool:
    expected = _sign(
        row["entry_id"], row["agent_id"], row["resource"],
        row["units"], row["cost_usd"], row["recorded_at"]
    )
    return hmac.compare_digest(expected, row["hmac"])


# ── Broadcast ─────────────────────────────────────────────────────────────────

async def _broadcast(event: str, payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{COMM_URL}/send", json={
                "from": "ledger",
                "to":   "ledger-events",
                "payload": {"event": event, **payload},
            })
    except Exception:
        pass


def _check_budget_breach(conn: sqlite3.Connection, agent_id: str, new_cost: float) -> Optional[dict]:
    """Check if this entry pushes the agent over budget. Returns breach info or None."""
    budget = conn.execute(
        "SELECT * FROM budgets WHERE agent_id=?", (agent_id,)
    ).fetchone()
    if not budget:
        return None

    day_start = time.time() - 86400
    month_start = time.time() - (30 * 86400)

    day_spent = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) as total FROM entries WHERE agent_id=? AND recorded_at>=?",
        (agent_id, day_start)
    ).fetchone()["total"] + new_cost

    month_spent = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) as total FROM entries WHERE agent_id=? AND recorded_at>=?",
        (agent_id, month_start)
    ).fetchone()["total"] + new_cost

    alerts = []
    if budget["daily_usd"] > 0:
        pct = (day_spent / budget["daily_usd"]) * 100
        if pct >= budget["alert_pct"]:
            alerts.append({"period": "daily", "spent": day_spent,
                           "budget": budget["daily_usd"], "pct": round(pct, 1)})
    if budget["monthly_usd"] > 0:
        pct = (month_spent / budget["monthly_usd"]) * 100
        if pct >= budget["alert_pct"]:
            alerts.append({"period": "monthly", "spent": month_spent,
                           "budget": budget["monthly_usd"], "pct": round(pct, 1)})
    return alerts or None


# ── Request / Response models ─────────────────────────────────────────────────

class EntryRequest(BaseModel):
    agent_id:   str
    resource:   str                   # e.g. "openai/gpt-4o", "anthropic/claude-3-5", "ollama/llama3"
    units:      float = 0
    unit_type:  str   = "tokens"      # tokens | seconds | requests | bytes
    cost_usd:   float = 0.0
    task_id:    str   = ""
    session_id: str   = ""
    metadata:   dict[str, Any] = Field(default_factory=dict)


class BudgetRequest(BaseModel):
    daily_usd:   float = 0
    monthly_usd: float = 0
    alert_pct:   float = 80.0         # alert when spend reaches this % of budget


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/entries", status_code=201)
async def record_entry(req: EntryRequest):
    """Record a cost entry. Append-only, HMAC-signed."""
    import uuid as _uuid
    entry_id    = str(_uuid.uuid4())
    recorded_at = time.time()
    sig         = _sign(entry_id, req.agent_id, req.resource,
                        req.units, req.cost_usd, recorded_at)

    with db() as conn:
        conn.execute("""
            INSERT INTO entries
              (entry_id, agent_id, resource, units, unit_type,
               cost_usd, task_id, session_id, metadata, recorded_at, hmac)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            entry_id, req.agent_id, req.resource, req.units, req.unit_type,
            req.cost_usd, req.task_id, req.session_id,
            json.dumps(req.metadata), recorded_at, sig,
        ))
        alerts = _check_budget_breach(conn, req.agent_id, req.cost_usd)

    if alerts:
        asyncio.create_task(_broadcast("budget_alert", {
            "agent_id": req.agent_id,
            "alerts":   alerts,
        }))

    if req.cost_usd > 0:
        asyncio.create_task(_broadcast("entry_recorded", {
            "agent_id": req.agent_id,
            "resource": req.resource,
            "cost_usd": req.cost_usd,
        }))

    return {
        "ok":         True,
        "entry_id":   entry_id,
        "hmac":       sig,
        "recorded_at": recorded_at,
        "budget_alerts": alerts,
    }


@app.get("/entries")
async def list_entries(
    agent_id:   str   = "",
    resource:   str   = "",
    since:      float = 0.0,    # unix timestamp
    until:      float = 0.0,
    limit:      int   = 100,
):
    clauses = []
    params: list = []
    if agent_id:
        clauses.append("agent_id=?")
        params.append(agent_id)
    if resource:
        clauses.append("resource=?")
        params.append(resource)
    if since:
        clauses.append("recorded_at>=?")
        params.append(since)
    if until:
        clauses.append("recorded_at<=?")
        params.append(until)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM entries {where} ORDER BY recorded_at DESC LIMIT ?",
            params
        ).fetchall()

    return {
        "ok":    True,
        "count": len(rows),
        "entries": [
            {
                "entry_id":   r["entry_id"],
                "agent_id":   r["agent_id"],
                "resource":   r["resource"],
                "units":      r["units"],
                "unit_type":  r["unit_type"],
                "cost_usd":   r["cost_usd"],
                "task_id":    r["task_id"],
                "session_id": r["session_id"],
                "recorded_at": r["recorded_at"],
                "hmac_valid": _verify(r),
            }
            for r in rows
        ]
    }


@app.get("/entries/{entry_id}")
async def get_entry(entry_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM entries WHERE entry_id=?", (entry_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {
        "ok":         True,
        "entry_id":   row["entry_id"],
        "agent_id":   row["agent_id"],
        "resource":   row["resource"],
        "units":      row["units"],
        "unit_type":  row["unit_type"],
        "cost_usd":   row["cost_usd"],
        "task_id":    row["task_id"],
        "session_id": row["session_id"],
        "metadata":   json.loads(row["metadata"]),
        "recorded_at": row["recorded_at"],
        "hmac_valid": _verify(row),
    }


@app.get("/summary/{agent_id}")
async def agent_summary(agent_id: str, since: float = 0.0):
    clause = "AND recorded_at>=?" if since else ""
    params = [agent_id] + ([since] if since else [])
    with db() as conn:
        rows = conn.execute(f"""
            SELECT resource, unit_type,
                   SUM(units) as total_units,
                   SUM(cost_usd) as total_cost,
                   COUNT(*) as n_entries
            FROM entries
            WHERE agent_id=? {clause}
            GROUP BY resource, unit_type
            ORDER BY total_cost DESC
        """, params).fetchall()

        total = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd),0) as t FROM entries WHERE agent_id=? {clause}",
            params
        ).fetchone()["t"]

    return {
        "ok":        True,
        "agent_id":  agent_id,
        "total_usd": round(total, 6),
        "breakdown": [
            {
                "resource":    r["resource"],
                "unit_type":   r["unit_type"],
                "total_units": r["total_units"],
                "total_cost":  round(r["total_cost"], 6),
                "entries":     r["n_entries"],
            }
            for r in rows
        ]
    }


@app.get("/summary")
async def system_summary(since: float = 0.0):
    clause = "WHERE recorded_at>=?" if since else ""
    params = [since] if since else []
    with db() as conn:
        rows = conn.execute(f"""
            SELECT agent_id,
                   SUM(cost_usd) as total_cost,
                   COUNT(*) as n_entries
            FROM entries {clause}
            GROUP BY agent_id
            ORDER BY total_cost DESC
        """, params).fetchall()

        total = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd),0) as t FROM entries {clause}", params
        ).fetchone()["t"]

    return {
        "ok":        True,
        "total_usd": round(total, 6),
        "agents": [
            {
                "agent_id":  r["agent_id"],
                "total_usd": round(r["total_cost"], 6),
                "entries":   r["n_entries"],
            }
            for r in rows
        ]
    }


@app.post("/budget/{agent_id}", status_code=201)
async def set_budget(agent_id: str, req: BudgetRequest):
    now = time.time()
    with db() as conn:
        conn.execute("""
            INSERT INTO budgets (agent_id, daily_usd, monthly_usd, alert_pct, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
              daily_usd=excluded.daily_usd,
              monthly_usd=excluded.monthly_usd,
              alert_pct=excluded.alert_pct,
              updated_at=excluded.updated_at
        """, (agent_id, req.daily_usd, req.monthly_usd, req.alert_pct, now))
    return {"ok": True, "agent_id": agent_id}


@app.get("/budget/{agent_id}")
async def get_budget(agent_id: str):
    with db() as conn:
        budget = conn.execute(
            "SELECT * FROM budgets WHERE agent_id=?", (agent_id,)
        ).fetchone()

        day_start   = time.time() - 86400
        month_start = time.time() - (30 * 86400)

        day_spent = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) as t FROM entries WHERE agent_id=? AND recorded_at>=?",
            (agent_id, day_start)
        ).fetchone()["t"]

        month_spent = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) as t FROM entries WHERE agent_id=? AND recorded_at>=?",
            (agent_id, month_start)
        ).fetchone()["t"]

    return {
        "ok":          True,
        "agent_id":    agent_id,
        "budget":      dict(budget) if budget else None,
        "day_spent":   round(day_spent, 6),
        "month_spent": round(month_spent, 6),
        "day_pct":     round((day_spent / budget["daily_usd"] * 100) if budget and budget["daily_usd"] else 0, 1),
        "month_pct":   round((month_spent / budget["monthly_usd"] * 100) if budget and budget["monthly_usd"] else 0, 1),
    }


@app.get("/health")
async def health():
    with db() as conn:
        entries = conn.execute("SELECT COUNT(*) as n FROM entries").fetchone()["n"]
        agents  = conn.execute("SELECT COUNT(DISTINCT agent_id) as n FROM entries").fetchone()["n"]
    return {"ok": True, "entries": entries, "agents": agents, "port": PORT}


@app.get("/stats")
async def stats():
    with db() as conn:
        total_entries = conn.execute("SELECT COUNT(*) as n FROM entries").fetchone()["n"]
        total_cost    = conn.execute("SELECT COALESCE(SUM(cost_usd),0) as t FROM entries").fetchone()["t"]
        agents        = conn.execute("SELECT COUNT(DISTINCT agent_id) as n FROM entries").fetchone()["n"]
        resources     = conn.execute("SELECT COUNT(DISTINCT resource) as n FROM entries").fetchone()["n"]
        budgets       = conn.execute("SELECT COUNT(*) as n FROM budgets").fetchone()["n"]
    return {
        "ok":           True,
        "total_entries": total_entries,
        "total_cost_usd": round(total_cost, 6),
        "agents":       agents,
        "resources":    resources,
        "budgets":      budgets,
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
