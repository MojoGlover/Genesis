"""
system_logger module — centralized error and event logging for all PlugOps agents.

Every agent can POST structured logs here. The dashboard reads summaries,
per-agent streams, and error reports through this module's REST API.

Routes:
    POST /logs/ingest                  — agent submits a log entry
    POST /logs/ingest/batch            — agent submits multiple entries at once
    GET  /logs                         — query logs (filter by agent, level, since)
    GET  /logs/agents/{agent_id}       — log stream for a single agent
    GET  /logs/errors                  — all errors + criticals across all agents
    GET  /logs/summary                 — per-agent counts, last-seen, last-error
    GET  /logs/stats                   — store-level stats (total rows, DB path)
    DELETE /logs/agents/{agent_id}     — clear one agent's logs
    DELETE /logs/all                   — wipe everything (use with care)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from modules.base import ModuleBase
from .log_store import get_store
from .schemas import IngestResponse, LogEntry, LogQuery, LogSummary

logger = logging.getLogger("system_logger")


class Module(ModuleBase):
    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:        return "system-logger"
    @property
    def version(self) -> str:     return "1.0.0"
    @property
    def description(self) -> str:
        return "Centralized structured logging for all PlugOps agents — errors, warnings, events."

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_startup(self) -> None:
        store = get_store()
        stats = store.stats()
        logger.info(
            f"system_logger online — {stats['total_logs']} logs from "
            f"{stats['agents_seen']} agents in store"
        )

    # ── Routes ────────────────────────────────────────────────────────────────

    @property
    def router(self) -> APIRouter:
        r = APIRouter(prefix="/logs", tags=["system-logger"])

        # ── Ingest ────────────────────────────────────────────────────────────

        @r.post("/ingest", response_model=IngestResponse, summary="Submit a log entry")
        async def ingest(entry: LogEntry):
            store = get_store()
            log_id = store.ingest(entry)
            ts = entry.timestamp or datetime.now(timezone.utc)
            if entry.level.value in ("error", "critical"):
                logger.error(f"[{entry.agent_name}] {entry.message}")
            return IngestResponse(ok=True, log_id=log_id, timestamp=ts)

        @r.post("/ingest/batch", summary="Submit multiple log entries at once")
        async def ingest_batch(entries: List[LogEntry]):
            store = get_store()
            ids = []
            for entry in entries:
                ids.append(store.ingest(entry))
            return {"ok": True, "count": len(ids), "log_ids": ids}

        # ── Query ─────────────────────────────────────────────────────────────

        @r.get("", summary="Query logs with optional filters")
        async def get_logs(
            agent_id: Optional[str]  = Query(None),
            level:    Optional[str]  = Query(None),
            since:    Optional[str]  = Query(None, description="ISO timestamp"),
            limit:    int            = Query(100, le=1000),
        ):
            store = get_store()
            rows = store.query(agent_id=agent_id, level=level, since=since, limit=limit)
            return {"count": len(rows), "logs": rows}

        @r.get("/agents/{agent_id}", summary="Log stream for a specific agent")
        async def get_agent_logs(
            agent_id: str,
            level:    Optional[str] = Query(None),
            limit:    int           = Query(100, le=1000),
        ):
            store = get_store()
            rows = store.query(agent_id=agent_id, level=level, limit=limit)
            return {"agent_id": agent_id, "count": len(rows), "logs": rows}

        @r.get("/errors", summary="All errors and criticals across all agents")
        async def get_errors(limit: int = Query(100, le=500)):
            store = get_store()
            rows = store.get_errors(limit=limit)
            return {"count": len(rows), "errors": rows}

        @r.get("/summary", response_model=List[LogSummary], summary="Per-agent summary")
        async def get_summary():
            store = get_store()
            return store.get_summaries()

        @r.get("/stats", summary="Store-level statistics")
        async def get_stats():
            store = get_store()
            return store.stats()

        # ── Clear ─────────────────────────────────────────────────────────────

        @r.delete("/agents/{agent_id}", summary="Clear all logs for one agent")
        async def clear_agent(agent_id: str):
            store = get_store()
            count = store.clear_agent(agent_id)
            logger.warning(f"Cleared {count} logs for agent {agent_id}")
            return {"ok": True, "deleted": count, "agent_id": agent_id}

        @r.delete("/all", summary="Wipe all logs from all agents")
        async def clear_all():
            store = get_store()
            count = store.clear_all()
            logger.warning(f"All logs cleared — {count} entries deleted")
            return {"ok": True, "deleted": count}

        return r

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        try:
            store = get_store()
            stats = store.stats()
            return {
                "status":       "ok",
                "module":       self.name,
                "version":      self.version,
                "total_logs":   stats["total_logs"],
                "total_errors": stats["total_errors"],
                "agents_seen":  stats["agents_seen"],
            }
        except Exception as e:
            return {
                "status":  "error",
                "module":  self.name,
                "version": self.version,
                "error":   str(e),
            }
