"""
Mind state client — persistent memory across restarts.

Agents call get_recent() at the start of each conversation (recall node)
and save() at the end (respond node). If the module is down, a local
SQLite fallback is used transparently.
"""
from __future__ import annotations
import logging
import sqlite3
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_FALLBACK_DB: dict[str, sqlite3.Connection] = {}


class MindStateClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True,
                 local_fallback_dir: Path | None = None):
        self.agent_id   = agent_id
        self.url        = url.rstrip("/")
        self.enabled    = enabled
        self._fallback  = local_fallback_dir  # set by main.py via data_dir

    def set_fallback_dir(self, path: Path) -> None:
        self._fallback = path

    # ── Remote ────────────────────────────────────────────────────────────────

    def get_recent(self, session_id: str, limit: int = 6) -> list[str]:
        """Fetch recent conversation turns for context. Never raises."""
        if self.enabled:
            try:
                r = httpx.get(f"{self.url}/state/{self.agent_id}", params={
                    "session_id": session_id, "limit": limit,
                }, timeout=3.0)
                if r.status_code == 200:
                    entries = r.json().get("entries", [])
                    return [f"{e['role']}: {e['content']}" for e in entries]
            except Exception:
                pass
        return self._local_get(session_id, limit)

    def save(self, session_id: str, human: str, assistant: str) -> None:
        """Save a human/assistant exchange. Never raises."""
        if self.enabled:
            try:
                httpx.post(f"{self.url}/state/{self.agent_id}", json={
                    "session_id": session_id,
                    "entries": [
                        {"role": "human",     "content": human},
                        {"role": "assistant", "content": assistant},
                    ],
                }, timeout=3.0)
                return
            except Exception:
                pass
        self._local_save(session_id, human, assistant)

    def restore(self) -> dict | None:
        """
        Check for MIND_STATE_RESTORE_VERSION env var (set by supervisor on restart).
        If present, pull full state from the module. Used by supervisor for Agent Hospital.
        """
        import os
        version = os.environ.get("MIND_STATE_RESTORE_VERSION")
        if not version or not self.enabled:
            return None
        try:
            r = httpx.get(f"{self.url}/restore/{self.agent_id}",
                          params={"version": version}, timeout=5.0)
            if r.status_code == 200:
                logger.info(f"[mind_state] Restored from version {version}")
                return r.json()
        except Exception as e:
            logger.warning(f"[mind_state] Restore failed: {e}")
        return None

    # ── Local SQLite fallback ─────────────────────────────────────────────────

    def _db(self) -> sqlite3.Connection | None:
        if not self._fallback:
            return None
        db_path = self._fallback / "memory.db"
        if str(db_path) not in _FALLBACK_DB:
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts TEXT NOT NULL
                )
            """)
            conn.commit()
            _FALLBACK_DB[str(db_path)] = conn
        return _FALLBACK_DB[str(db_path)]

    def _local_get(self, session_id: str, limit: int) -> list[str]:
        try:
            conn = self._db()
            if not conn:
                return []
            rows = conn.execute(
                "SELECT role, content FROM conversations "
                "WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [f"{role}: {content}" for role, content in reversed(rows)]
        except Exception:
            return []

    def _local_save(self, session_id: str, human: str, assistant: str) -> None:
        try:
            conn = self._db()
            if not conn:
                return
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            conn.execute(
                "INSERT INTO conversations (session_id,role,content,ts) VALUES (?,?,?,?)",
                (session_id, "human", human, ts),
            )
            conn.execute(
                "INSERT INTO conversations (session_id,role,content,ts) VALUES (?,?,?,?)",
                (session_id, "assistant", assistant, ts),
            )
            conn.commit()
        except Exception:
            pass
