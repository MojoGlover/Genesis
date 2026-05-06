"""
Mind state client — persistent memory across restarts.

TWO distinct jobs:

  1. Conversation history (get_recent / save)
     High-frequency per-turn storage. Always uses local SQLite.
     The mind_state MODULE SERVER is a versioned state-snapshot system —
     it is NOT designed for per-turn conversation logs. Using it here would
     create one new version per conversation turn, which is wrong.
     SQLite is the right tool: fast, local, append-only.

  2. Full state snapshots (restore)
     Low-frequency. Used by Agent Hospital on restart to recover agent context.
     Calls the module server's /agents/{id}/state endpoint.

set_fallback_dir() MUST be called before get_recent()/save() will work.
The recall node calls it on every invocation via state["_data_dir"].
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
        self.agent_id  = agent_id
        self.url       = url.rstrip("/")
        self.enabled   = enabled
        self._fallback = local_fallback_dir

    def set_fallback_dir(self, path: Path) -> None:
        self._fallback = path

    # ── Conversation history — SQLite only ────────────────────────────────────

    def get_recent(self, session_id: str, limit: int = 6) -> list[str]:
        """Return recent conversation turns for context injection. Never raises."""
        return self._local_get(session_id, limit)

    def save(self, session_id: str, human: str, assistant: str) -> None:
        """Persist a human/assistant exchange to local SQLite. Never raises."""
        self._local_save(session_id, human, assistant)

    # ── Full state snapshots — module server ──────────────────────────────────

    def restore(self) -> dict | None:
        """
        Pull the agent's last saved state snapshot from the module server.
        Called by Agent Hospital on restart (MIND_STATE_RESTORE_VERSION env var).
        Returns the state dict, or None if nothing to restore.
        """
        import os
        version = os.environ.get("MIND_STATE_RESTORE_VERSION")
        if not version or not self.enabled:
            return None
        try:
            r = httpx.get(
                f"{self.url}/agents/{self.agent_id}/state/{version}",
                timeout=5.0,
            )
            if r.status_code == 200:
                data = r.json()
                logger.info(f"[mind_state] Restored v{version} for {self.agent_id}")
                return data.get("state")
        except Exception as e:
            logger.warning(f"[mind_state] Restore failed: {e}")
        return None

    def save_snapshot(self, state: dict, label: str = "") -> None:
        """
        Save a full state snapshot to the module server (Agent Hospital use).
        Agents can call this at meaningful checkpoints — not every turn.
        """
        if not self.enabled:
            return
        try:
            httpx.post(
                f"{self.url}/agents/{self.agent_id}/state",
                json={"state": state, "snapshot_type": "auto", "label": label},
                timeout=5.0,
            )
        except Exception as e:
            logger.warning(f"[mind_state] save_snapshot failed: {e}")

    # ── SQLite ────────────────────────────────────────────────────────────────

    def _db(self) -> sqlite3.Connection | None:
        if not self._fallback:
            return None
        db_path = self._fallback / "memory.db"
        key = str(db_path)
        if key not in _FALLBACK_DB:
            conn = sqlite3.connect(key)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT    NOT NULL,
                    role       TEXT    NOT NULL,
                    content    TEXT    NOT NULL,
                    ts         TEXT    NOT NULL
                )
            """)
            conn.commit()
            _FALLBACK_DB[key] = conn
        return _FALLBACK_DB[key]

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
