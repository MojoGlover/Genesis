"""
observability node — system-wide metrics, traces, and agent health monitoring.

Every agent pushes metrics and spans. Observability aggregates, retains, and
exposes them for dashboards, alerting, and debugging.

What gets tracked:
  metrics  — counters, gauges, histograms per agent (tasks/sec, latency, errors)
  spans    — per-request trace spans (start/end/duration/status)
  health   — periodic agent health beats (CPU, memory, queue depth, model latency)
  alerts   — threshold-based alerting

HTTP API (port 9108):
  POST   /metrics                push a metric data point
  POST   /metrics/batch          push multiple metrics at once
  GET    /metrics/{agent_id}     recent metrics for an agent
  GET    /metrics/aggregate      aggregate across agents (sum/avg/max by metric_name)
  POST   /spans                  start or complete a trace span
  GET    /spans/{trace_id}       get all spans for a trace
  POST   /health                 push health beat from an agent
  GET    /health                 current health snapshot for all agents
  GET    /health/{agent_id}      health snapshot for one agent
  GET    /alerts                 active alert conditions
  GET    /summary                overall system summary
  GET    /health_check           node health check
  GET    /stats                  node stats
"""
from __future__ import annotations

import asyncio
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

PORT           = 9108
COMM_URL       = "http://127.0.0.1:9100"
DB_PATH        = Path(__file__).parent / "observability.db"

METRIC_KEEP    = 50_000    # max metric points retained
SPAN_KEEP      = 10_000    # max spans retained
HEALTH_TTL     = 120       # seconds before health beat considered stale
ALERT_CHECK_INTERVAL = 30  # seconds between alert evaluations

app = FastAPI(title="Observability Node", version="1.0")


# ── DB ────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS metrics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id    TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_type TEXT NOT NULL DEFAULT 'gauge',
                value       REAL NOT NULL,
                labels      TEXT NOT NULL DEFAULT '{}',
                recorded_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_agent
                ON metrics(agent_id, metric_name, recorded_at DESC);
            CREATE INDEX IF NOT EXISTS idx_metrics_name
                ON metrics(metric_name, recorded_at DESC);

            CREATE TABLE IF NOT EXISTS spans (
                span_id     TEXT PRIMARY KEY,
                trace_id    TEXT NOT NULL,
                parent_id   TEXT NOT NULL DEFAULT '',
                agent_id    TEXT NOT NULL,
                name        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'ok',
                started_at  REAL NOT NULL,
                ended_at    REAL,
                duration_ms REAL,
                labels      TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_spans_trace
                ON spans(trace_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_spans_agent
                ON spans(agent_id, started_at DESC);

            CREATE TABLE IF NOT EXISTS health_beats (
                agent_id      TEXT PRIMARY KEY,
                status        TEXT NOT NULL DEFAULT 'ok',
                cpu_pct       REAL,
                mem_mb        REAL,
                queue_depth   INTEGER,
                model_latency_ms REAL,
                extra         TEXT NOT NULL DEFAULT '{}',
                beat_at       REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_rules (
                rule_id     TEXT PRIMARY KEY,
                metric_name TEXT NOT NULL,
                condition   TEXT NOT NULL,
                threshold   REAL NOT NULL,
                agent_id    TEXT NOT NULL DEFAULT '',
                severity    TEXT NOT NULL DEFAULT 'warning',
                message     TEXT NOT NULL DEFAULT '',
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS alert_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id     TEXT NOT NULL,
                agent_id    TEXT NOT NULL,
                value       REAL NOT NULL,
                severity    TEXT NOT NULL,
                message     TEXT NOT NULL,
                fired_at    REAL NOT NULL,
                resolved_at REAL
            );
        """)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _broadcast(event: str, payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{COMM_URL}/send", json={
                "from": "observability",
                "to":   "obs-events",
                "payload": {"event": event, **payload},
            })
    except Exception:
        pass


def _prune(conn: sqlite3.Connection) -> None:
    conn.execute("""
        DELETE FROM metrics WHERE id NOT IN (
            SELECT id FROM metrics ORDER BY id DESC LIMIT ?
        )
    """, (METRIC_KEEP,))
    conn.execute("""
        DELETE FROM spans WHERE rowid NOT IN (
            SELECT rowid FROM spans ORDER BY rowid DESC LIMIT ?
        )
    """, (SPAN_KEEP,))


# ── Request / Response models ─────────────────────────────────────────────────

class MetricPoint(BaseModel):
    agent_id:    str
    metric_name: str
    metric_type: str = "gauge"   # gauge | counter | histogram
    value:       float
    labels:      dict[str, Any] = Field(default_factory=dict)


class MetricBatch(BaseModel):
    points: list[MetricPoint]


class SpanRequest(BaseModel):
    span_id:   str
    trace_id:  str
    parent_id: str = ""
    agent_id:  str
    name:      str
    status:    str  = "ok"       # ok | error
    started_at: float
    ended_at:   Optional[float] = None
    labels:    dict[str, Any] = Field(default_factory=dict)


class HealthBeat(BaseModel):
    agent_id:         str
    status:           str   = "ok"   # ok | degraded | critical
    cpu_pct:          Optional[float] = None
    mem_mb:           Optional[float] = None
    queue_depth:      Optional[int]   = None
    model_latency_ms: Optional[float] = None
    extra:            dict[str, Any]  = Field(default_factory=dict)


class AlertRule(BaseModel):
    rule_id:    str
    metric_name: str
    condition:  str    # gt | lt | gte | lte | eq
    threshold:  float
    agent_id:   str  = ""
    severity:   str  = "warning"
    message:    str  = ""
    enabled:    bool = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/metrics", status_code=201)
async def push_metric(req: MetricPoint):
    now = time.time()
    with db() as conn:
        conn.execute("""
            INSERT INTO metrics (agent_id, metric_name, metric_type, value, labels, recorded_at)
            VALUES (?,?,?,?,?,?)
        """, (req.agent_id, req.metric_name, req.metric_type,
              req.value, json.dumps(req.labels), now))
        _prune(conn)
    return {"ok": True, "recorded_at": now}


@app.post("/metrics/batch", status_code=201)
async def push_metrics_batch(req: MetricBatch):
    now = time.time()
    with db() as conn:
        for pt in req.points:
            conn.execute("""
                INSERT INTO metrics (agent_id, metric_name, metric_type, value, labels, recorded_at)
                VALUES (?,?,?,?,?,?)
            """, (pt.agent_id, pt.metric_name, pt.metric_type,
                  pt.value, json.dumps(pt.labels), now))
        _prune(conn)
    return {"ok": True, "count": len(req.points), "recorded_at": now}


@app.get("/metrics/{agent_id}")
async def get_agent_metrics(agent_id: str, metric_name: str = "", limit: int = 100, since: float = 0):
    clauses = ["agent_id=?"]
    params: list = [agent_id]
    if metric_name:
        clauses.append("metric_name=?")
        params.append(metric_name)
    if since:
        clauses.append("recorded_at>=?")
        params.append(since)
    params.append(limit)

    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM metrics WHERE {' AND '.join(clauses)} ORDER BY recorded_at DESC LIMIT ?",
            params
        ).fetchall()

    return {
        "ok":       True,
        "agent_id": agent_id,
        "count":    len(rows),
        "metrics": [
            {
                "metric_name": r["metric_name"],
                "metric_type": r["metric_type"],
                "value":       r["value"],
                "labels":      json.loads(r["labels"]),
                "recorded_at": r["recorded_at"],
            }
            for r in rows
        ]
    }


@app.get("/metrics/aggregate")
async def aggregate_metrics(metric_name: str, fn: str = "avg", since: float = 0):
    """Aggregate a metric across all agents. fn: avg | sum | max | min | count"""
    agg_fns = {"avg": "AVG", "sum": "SUM", "max": "MAX", "min": "MIN", "count": "COUNT"}
    if fn not in agg_fns:
        raise HTTPException(status_code=422, detail={"error": f"Unknown fn: {fn}"})

    sql_fn = agg_fns[fn]
    clause = "AND recorded_at>=?" if since else ""
    params = [metric_name] + ([since] if since else [])

    with db() as conn:
        rows = conn.execute(f"""
            SELECT agent_id, {sql_fn}(value) as result, COUNT(*) as n
            FROM metrics
            WHERE metric_name=? {clause}
            GROUP BY agent_id
            ORDER BY result DESC
        """, params).fetchall()

    return {
        "ok":          True,
        "metric_name": metric_name,
        "fn":          fn,
        "results": [
            {"agent_id": r["agent_id"], "value": r["result"], "n": r["n"]}
            for r in rows
        ]
    }


@app.post("/spans", status_code=201)
async def push_span(req: SpanRequest):
    duration = None
    if req.ended_at and req.started_at:
        duration = (req.ended_at - req.started_at) * 1000

    with db() as conn:
        conn.execute("""
            INSERT INTO spans
              (span_id, trace_id, parent_id, agent_id, name, status,
               started_at, ended_at, duration_ms, labels)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(span_id) DO UPDATE SET
              status=excluded.status, ended_at=excluded.ended_at,
              duration_ms=excluded.duration_ms
        """, (
            req.span_id, req.trace_id, req.parent_id, req.agent_id,
            req.name, req.status, req.started_at, req.ended_at, duration,
            json.dumps(req.labels),
        ))

    return {"ok": True, "span_id": req.span_id, "duration_ms": duration}


@app.get("/spans/{trace_id}")
async def get_trace(trace_id: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM spans WHERE trace_id=? ORDER BY started_at",
            (trace_id,)
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "trace_not_found"})
    return {
        "ok":       True,
        "trace_id": trace_id,
        "spans": [
            {
                "span_id":     r["span_id"],
                "parent_id":   r["parent_id"],
                "agent_id":    r["agent_id"],
                "name":        r["name"],
                "status":      r["status"],
                "started_at":  r["started_at"],
                "ended_at":    r["ended_at"],
                "duration_ms": r["duration_ms"],
            }
            for r in rows
        ]
    }


@app.post("/health", status_code=201)
async def push_health(req: HealthBeat):
    now = time.time()
    with db() as conn:
        conn.execute("""
            INSERT INTO health_beats
              (agent_id, status, cpu_pct, mem_mb, queue_depth, model_latency_ms, extra, beat_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
              status=excluded.status, cpu_pct=excluded.cpu_pct,
              mem_mb=excluded.mem_mb, queue_depth=excluded.queue_depth,
              model_latency_ms=excluded.model_latency_ms,
              extra=excluded.extra, beat_at=excluded.beat_at
        """, (
            req.agent_id, req.status, req.cpu_pct, req.mem_mb,
            req.queue_depth, req.model_latency_ms,
            json.dumps(req.extra), now,
        ))

    if req.status in ("degraded", "critical"):
        asyncio.create_task(_broadcast("agent_health_alert", {
            "agent_id": req.agent_id,
            "status":   req.status,
        }))

    return {"ok": True, "agent_id": req.agent_id, "beat_at": now}


@app.get("/health")
async def get_all_health():
    stale_cutoff = time.time() - HEALTH_TTL
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM health_beats ORDER BY beat_at DESC"
        ).fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "agents": [
            {
                "agent_id":         r["agent_id"],
                "status":           r["status"] if r["beat_at"] >= stale_cutoff else "stale",
                "cpu_pct":          r["cpu_pct"],
                "mem_mb":           r["mem_mb"],
                "queue_depth":      r["queue_depth"],
                "model_latency_ms": r["model_latency_ms"],
                "beat_at":          r["beat_at"],
                "stale":            r["beat_at"] < stale_cutoff,
            }
            for r in rows
        ]
    }


@app.get("/health/{agent_id}")
async def get_agent_health(agent_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM health_beats WHERE agent_id=?", (agent_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "no_health_data"})
    stale = row["beat_at"] < (time.time() - HEALTH_TTL)
    return {
        "ok":               True,
        "agent_id":         row["agent_id"],
        "status":           "stale" if stale else row["status"],
        "cpu_pct":          row["cpu_pct"],
        "mem_mb":           row["mem_mb"],
        "queue_depth":      row["queue_depth"],
        "model_latency_ms": row["model_latency_ms"],
        "extra":            json.loads(row["extra"]),
        "beat_at":          row["beat_at"],
        "stale":            stale,
    }


@app.post("/alerts/rules", status_code=201)
async def create_alert_rule(req: AlertRule):
    now = time.time()
    with db() as conn:
        conn.execute("""
            INSERT INTO alert_rules
              (rule_id, metric_name, condition, threshold, agent_id,
               severity, message, enabled, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(rule_id) DO UPDATE SET
              metric_name=excluded.metric_name, condition=excluded.condition,
              threshold=excluded.threshold, agent_id=excluded.agent_id,
              severity=excluded.severity, message=excluded.message,
              enabled=excluded.enabled
        """, (
            req.rule_id, req.metric_name, req.condition, req.threshold,
            req.agent_id, req.severity, req.message, int(req.enabled), now,
        ))
    return {"ok": True, "rule_id": req.rule_id}


@app.get("/alerts")
async def get_alerts(resolved: bool = False):
    with db() as conn:
        if resolved:
            rows = conn.execute(
                "SELECT * FROM alert_events ORDER BY fired_at DESC LIMIT 100"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alert_events WHERE resolved_at IS NULL ORDER BY fired_at DESC"
            ).fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "alerts": [dict(r) for r in rows]
    }


@app.get("/summary")
async def system_summary():
    with db() as conn:
        agents_with_metrics = conn.execute(
            "SELECT COUNT(DISTINCT agent_id) as n FROM metrics"
        ).fetchone()["n"]
        agents_with_health  = conn.execute(
            "SELECT COUNT(*) as n FROM health_beats"
        ).fetchone()["n"]
        healthy   = conn.execute(
            "SELECT COUNT(*) as n FROM health_beats WHERE status='ok'"
        ).fetchone()["n"]
        degraded  = conn.execute(
            "SELECT COUNT(*) as n FROM health_beats WHERE status IN ('degraded','critical')"
        ).fetchone()["n"]
        stale     = conn.execute(
            "SELECT COUNT(*) as n FROM health_beats WHERE beat_at<?", (time.time() - HEALTH_TTL,)
        ).fetchone()["n"]
        total_metrics = conn.execute("SELECT COUNT(*) as n FROM metrics").fetchone()["n"]
        total_spans   = conn.execute("SELECT COUNT(*) as n FROM spans").fetchone()["n"]

    return {
        "ok":                  True,
        "agents_with_metrics": agents_with_metrics,
        "agents_with_health":  agents_with_health,
        "healthy":             healthy,
        "degraded":            degraded,
        "stale":               stale,
        "total_metric_points": total_metrics,
        "total_spans":         total_spans,
    }


@app.get("/health_check")
async def health_check():
    with db() as conn:
        metrics = conn.execute("SELECT COUNT(*) as n FROM metrics").fetchone()["n"]
        agents  = conn.execute("SELECT COUNT(*) as n FROM health_beats").fetchone()["n"]
    return {"ok": True, "metric_points": metrics, "tracked_agents": agents, "port": PORT}


@app.get("/stats")
async def stats():
    with db() as conn:
        metric_pts  = conn.execute("SELECT COUNT(*) as n FROM metrics").fetchone()["n"]
        spans       = conn.execute("SELECT COUNT(*) as n FROM spans").fetchone()["n"]
        health_beat = conn.execute("SELECT COUNT(*) as n FROM health_beats").fetchone()["n"]
        alert_rules = conn.execute("SELECT COUNT(*) as n FROM alert_rules WHERE enabled=1").fetchone()["n"]
    return {
        "ok":              True,
        "metric_points":   metric_pts,
        "spans":           spans,
        "tracked_agents":  health_beat,
        "active_alerts":   alert_rules,
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
