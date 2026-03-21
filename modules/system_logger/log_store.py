"""
LogStore — SQLite-backed log storage with in-memory cache.

Each agent writes structured log entries. The store handles:
- Persistence via SQLite (survives restarts)
- Fast recent-log queries via in-memory ring buffer per agent
- Automatic rotation — keeps last MAX_ROWS rows per agent
- Thread-safe writes
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .schemas import LogEntry, LogLevel, LogSummary

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH     = Path.home() / ".plugops" / "system_logger.db"
MAX_ROWS    = 5_000   # per agent — older rows purged automatically
CACHE_SIZE  = 200     # in-memory ring buffer per agent


class LogStore:
    def __init__(self, db_path: Path = DB_PATH):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock    = threading.Lock()
        # In-memory cache: agent_id → deque of row dicts (most recent last)
        self._cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=CACHE_SIZE))
        self._init_db()
        self._warm_cache()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id          TEXT PRIMARY KEY,
                    agent_id    TEXT NOT NULL,
                    agent_name  TEXT NOT NULL,
                    level       TEXT NOT NULL,
                    message     TEXT NOT NULL,
                    context     TEXT,
                    ts          TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent ON logs(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_level  ON logs(level)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts     ON logs(ts)")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _warm_cache(self) -> None:
        """Load the most recent CACHE_SIZE rows per agent into memory on startup."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY agent_id ORDER BY ts DESC) AS rn
                    FROM logs
                ) WHERE rn <= ?
                ORDER BY ts ASC
            """, (CACHE_SIZE,)).fetchall()
        for row in rows:
            self._cache[row["agent_id"]].append(dict(row))

    # ── Write ─────────────────────────────────────────────────────────────────

    def ingest(self, entry: LogEntry) -> str:
        log_id = str(uuid.uuid4())
        ts     = (entry.timestamp or datetime.now(timezone.utc)).isoformat()
        row = {
            "id":         log_id,
            "agent_id":   entry.agent_id,
            "agent_name": entry.agent_name,
            "level":      entry.level.value,
            "message":    entry.message,
            "context":    json.dumps(entry.context) if entry.context else None,
            "ts":         ts,
        }
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO logs VALUES (:id,:agent_id,:agent_name,:level,:message,:context,:ts)",
                    row
                )
                # Purge old rows for this agent
                conn.execute("""
                    DELETE FROM logs WHERE agent_id = ? AND id NOT IN (
                        SELECT id FROM logs WHERE agent_id = ? ORDER BY ts DESC LIMIT ?
                    )
                """, (entry.agent_id, entry.agent_id, MAX_ROWS))
            self._cache[entry.agent_id].append(row)
        return log_id

    # ── Query ─────────────────────────────────────────────────────────────────

    def query(
        self,
        agent_id: Optional[str]   = None,
        level:    Optional[str]   = None,
        since:    Optional[str]   = None,
        limit:    int             = 100,
    ) -> List[dict]:
        # Try cache first for recent single-agent queries
        if agent_id and not since and limit <= CACHE_SIZE:
            rows = list(self._cache[agent_id])
            if level:
                rows = [r for r in rows if r["level"] == level]
            return rows[-limit:]

        # Fall through to DB for cross-agent or filtered queries
        clauses, params = [], []
        if agent_id:
            clauses.append("agent_id = ?"); params.append(agent_id)
        if level:
            clauses.append("level = ?"); params.append(level)
        if since:
            clauses.append("ts >= ?"); params.append(since)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM logs {where} ORDER BY ts DESC LIMIT ?",
                params
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_errors(self, limit: int = 100) -> List[dict]:
        return self.query(level="error", limit=limit) + \
               self.query(level="critical", limit=limit)

    def get_summaries(self) -> List[LogSummary]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    agent_id,
                    agent_name,
                    COUNT(*) AS total,
                    SUM(level IN ('error','critical')) AS errors,
                    SUM(level = 'warning') AS warnings,
                    MAX(ts) AS last_seen
                FROM logs
                GROUP BY agent_id
            """).fetchall()

            summaries = []
            for r in rows:
                # Last error details
                err = conn.execute("""
                    SELECT message, ts FROM logs
                    WHERE agent_id = ? AND level IN ('error','critical')
                    ORDER BY ts DESC LIMIT 1
                """, (r["agent_id"],)).fetchone()

                summaries.append(LogSummary(
                    agent_id      = r["agent_id"],
                    agent_name    = r["agent_name"],
                    total         = r["total"],
                    errors        = r["errors"] or 0,
                    warnings      = r["warnings"] or 0,
                    last_seen     = datetime.fromisoformat(r["last_seen"]) if r["last_seen"] else None,
                    last_error    = err["message"] if err else None,
                    last_error_at = datetime.fromisoformat(err["ts"]) if err else None,
                ))
        return summaries

    def clear_agent(self, agent_id: str) -> int:
        with self._lock:
            with self._conn() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM logs WHERE agent_id = ?", (agent_id,)
                ).fetchone()[0]
                conn.execute("DELETE FROM logs WHERE agent_id = ?", (agent_id,))
            self._cache.pop(agent_id, None)
        return count

    def clear_all(self) -> int:
        with self._lock:
            with self._conn() as conn:
                count = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
                conn.execute("DELETE FROM logs")
            self._cache.clear()
        return count

    def stats(self) -> dict:
        with self._conn() as conn:
            total  = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            errors = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE level IN ('error','critical')"
            ).fetchone()[0]
            agents = conn.execute(
                "SELECT COUNT(DISTINCT agent_id) FROM logs"
            ).fetchone()[0]
        return {
            "total_logs":   total,
            "total_errors": errors,
            "agents_seen":  agents,
            "db_path":      str(self._db_path),
            "max_rows_per_agent": MAX_ROWS,
        }


# Singleton
_store: Optional[LogStore] = None

def get_store() -> LogStore:
    global _store
    if _store is None:
        _store = LogStore()
    return _store
