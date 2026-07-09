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
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Bug found 2026-07-09: /api/chat runs graph.invoke() via loop.run_in_executor,
# which can hand different requests to different threadpool threads. sqlite3
# connections default to check_same_thread=True, so a connection cached here
# under one thread would silently fail (ProgrammingError) when reused from
# another — and _local_get/_local_save swallowed the exception entirely,
# so turns randomly vanished from conversation memory with zero trace in logs.
# Fix: check_same_thread=False (connection usable from any thread) + a lock
# per connection (a single sqlite3.Connection still isn't safe for truly
# concurrent access — the lock serializes it, which is fine at chat-request
# volume).
_FALLBACK_DB: dict[str, sqlite3.Connection] = {}
_FALLBACK_LOCKS: dict[str, threading.Lock] = {}


class MindStateClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True,
                 local_fallback_dir: Path | None = None,
                 plugops_url: str = ""):
        self.agent_id   = agent_id
        self.url        = url.rstrip("/")
        self.enabled    = enabled
        self._fallback  = local_fallback_dir
        # PlugOps mind_state REST URL — used for cross-host snapshots (Agent Hospital)
        # e.g. "https://plugzero-xyz.a.run.app"
        self._plugops   = plugops_url.rstrip("/")

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

    def pull_snapshot(self) -> dict | None:
        """
        Pull the latest state snapshot from PlugOps mind_state.
        Called on boot so the agent resumes where it left off (Agent Hospital / mobility).
        Returns the full snapshot dict, or None if none exists.
        """
        if not self._plugops:
            return None
        try:
            r = httpx.get(
                f"{self._plugops}/api/v1/mind_state/{self.agent_id}/snapshot",
                timeout=5.0,
            )
            if r.status_code == 200:
                snap = r.json()
                logger.info(f"[mind_state] Pulled snapshot v{snap.get('version')} for {self.agent_id}")
                return snap
        except Exception as e:
            logger.warning(f"[mind_state] pull_snapshot failed: {e}")
        return None

    def push_snapshot(self, session_history: list, task_queue: list,
                      working_memory: dict, host: str = "") -> None:
        """
        Push a full state snapshot to PlugOps mind_state.
        Call this before migration or at meaningful task checkpoints.
        """
        if not self._plugops:
            return
        import socket
        payload = {
            "agent_id":       self.agent_id,
            "session_history": session_history,
            "task_queue":     task_queue,
            "working_memory": working_memory,
            "host":           host or socket.gethostname(),
        }
        try:
            r = httpx.post(
                f"{self._plugops}/api/v1/mind_state/{self.agent_id}/snapshot",
                json=payload,
                timeout=5.0,
            )
            if r.status_code == 200:
                data = r.json()
                logger.info(f"[mind_state] Pushed snapshot v{data.get('version')} for {self.agent_id}")
        except Exception as e:
            logger.warning(f"[mind_state] push_snapshot failed: {e}")

    def restore(self) -> dict | None:
        """
        Pull the agent's last saved state snapshot.
        Checks PlugOps first (cross-host), falls back to local module server.
        Called by Agent Hospital on restart (MIND_STATE_RESTORE_VERSION env var).
        Returns the state dict, or None if nothing to restore.
        """
        import os
        # Try PlugOps snapshot first (supports cross-host recovery)
        snap = self.pull_snapshot()
        if snap:
            return snap

        # Legacy: local module server with version env var
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
        Save a full state snapshot (Agent Hospital use).
        Pushes to PlugOps if configured; falls back to local module server.
        """
        if not self.enabled:
            return
        # Push to PlugOps (preferred — cross-host)
        if self._plugops:
            self.push_snapshot(
                session_history=state.get("session_history", []),
                task_queue=state.get("task_queue", []),
                working_memory=state.get("working_memory", {}),
                host=state.get("host", ""),
            )
            return
        # Legacy: local module server
        try:
            httpx.post(
                f"{self.url}/agents/{self.agent_id}/state",
                json={"state": state, "snapshot_type": "auto", "label": label},
                timeout=5.0,
            )
        except Exception as e:
            logger.warning(f"[mind_state] save_snapshot failed: {e}")

    # ── SQLite ────────────────────────────────────────────────────────────────

    def _db(self) -> tuple[sqlite3.Connection, threading.Lock] | tuple[None, None]:
        if not self._fallback:
            return None, None
        db_path = self._fallback / "memory.db"
        key = str(db_path)
        if key not in _FALLBACK_DB:
            # check_same_thread=False: /api/chat invokes the graph via
            # run_in_executor, which can use a different thread per request.
            conn = sqlite3.connect(key, check_same_thread=False)
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
            _FALLBACK_LOCKS[key] = threading.Lock()
        return _FALLBACK_DB[key], _FALLBACK_LOCKS[key]

    def _local_get(self, session_id: str, limit: int) -> list[str]:
        try:
            conn, lock = self._db()
            if not conn:
                return []
            with lock:
                rows = conn.execute(
                    "SELECT role, content FROM conversations "
                    "WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            return [f"{role}: {content}" for role, content in reversed(rows)]
        except Exception as e:
            # Was a silent `except: return []` — the exact bug that made turns
            # vanish from memory with no trace. Log it now so a recurrence (or
            # a different failure mode) is visible instead of invisible.
            logger.error(f"[mind_state] get_recent failed for session={session_id!r}: {e!r}")
            return []

    def _local_save(self, session_id: str, human: str, assistant: str) -> None:
        try:
            conn, lock = self._db()
            if not conn:
                return
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            with lock:
                conn.execute(
                    "INSERT INTO conversations (session_id,role,content,ts) VALUES (?,?,?,?)",
                    (session_id, "human", human, ts),
                )
                conn.execute(
                    "INSERT INTO conversations (session_id,role,content,ts) VALUES (?,?,?,?)",
                    (session_id, "assistant", assistant, ts),
                )
                conn.commit()
        except Exception as e:
            # Was a silent `except: pass` — see _local_get comment above.
            logger.error(f"[mind_state] save failed for session={session_id!r}: {e!r}")
