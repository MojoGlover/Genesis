"""
Engineer0 Persistent Memory

Survives restarts, tracks:
- Current goals and tasks in progress
- Session state (what she was doing)
- Learning from past tasks
- Agent family status
- System observations
"""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single memory entry."""
    id: Optional[int]
    timestamp: str
    category: str  # task, goal, observation, learning, agent, system
    content: str
    metadata: Dict[str, Any]
    importance: float  # 0.0 - 1.0, for pruning old memories

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PersistentMemory:
    """
    SQLite-backed persistent memory for Engineer0.

    Categories:
    - task: Task execution history
    - goal: Goal progress
    - observation: System observations
    - learning: What she learned from tasks
    - agent: Agent family status
    - system: System state snapshots
    - resume: What to do on restart
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                importance REAL DEFAULT 0.5
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_category ON memories(category)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON memories(timestamp)
        """)

        # Resume state table (single row)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resume_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_updated TEXT,
                current_goal_id TEXT,
                current_task_id TEXT,
                session_context TEXT,
                pending_actions TEXT
            )
        """)

        # Ensure resume_state has a row
        cursor.execute("""
            INSERT OR IGNORE INTO resume_state (id, last_updated, session_context, pending_actions)
            VALUES (1, ?, '{}', '[]')
        """, (datetime.now().isoformat(),))

        conn.commit()
        conn.close()

    def remember(
        self,
        category: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 0.5
    ) -> int:
        """Store a memory."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO memories (timestamp, category, content, metadata, importance)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            category,
            content,
            json.dumps(metadata or {}),
            importance
        ))

        memory_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return memory_id

    def recall(
        self,
        category: Optional[str] = None,
        limit: int = 50,
        min_importance: float = 0.0,
        since: Optional[str] = None
    ) -> List[MemoryEntry]:
        """Recall memories with optional filtering."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT id, timestamp, category, content, metadata, importance FROM memories WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if min_importance > 0:
            query += " AND importance >= ?"
            params.append(min_importance)

        if since:
            query += " AND timestamp >= ?"
            params.append(since)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            MemoryEntry(
                id=row[0],
                timestamp=row[1],
                category=row[2],
                content=row[3],
                metadata=json.loads(row[4]) if row[4] else {},
                importance=row[5]
            )
            for row in rows
        ]

    def recall_by_keyword(self, keyword: str, limit: int = 20) -> List[MemoryEntry]:
        """Search memories by keyword."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, timestamp, category, content, metadata, importance
            FROM memories
            WHERE content LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f"%{keyword}%", limit))

        rows = cursor.fetchall()
        conn.close()

        return [
            MemoryEntry(
                id=row[0],
                timestamp=row[1],
                category=row[2],
                content=row[3],
                metadata=json.loads(row[4]) if row[4] else {},
                importance=row[5]
            )
            for row in rows
        ]

    def get_resume_state(self) -> Dict[str, Any]:
        """Get the state to resume from after restart."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT last_updated, current_goal_id, current_task_id, session_context, pending_actions
            FROM resume_state WHERE id = 1
        """)

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "last_updated": row[0],
                "current_goal_id": row[1],
                "current_task_id": row[2],
                "session_context": json.loads(row[3]) if row[3] else {},
                "pending_actions": json.loads(row[4]) if row[4] else []
            }

        return {}

    def save_resume_state(
        self,
        current_goal_id: Optional[str] = None,
        current_task_id: Optional[str] = None,
        session_context: Optional[Dict[str, Any]] = None,
        pending_actions: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """Save state for resuming after restart."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE resume_state SET
                last_updated = ?,
                current_goal_id = ?,
                current_task_id = ?,
                session_context = ?,
                pending_actions = ?
            WHERE id = 1
        """, (
            datetime.now().isoformat(),
            current_goal_id,
            current_task_id,
            json.dumps(session_context or {}),
            json.dumps(pending_actions or [])
        ))

        conn.commit()
        conn.close()

    def clear_resume_state(self) -> None:
        """Clear resume state after successful resume."""
        self.save_resume_state()

    def learn(self, lesson: str, context: Dict[str, Any], importance: float = 0.7) -> int:
        """Store a learning for future reference."""
        return self.remember(
            category="learning",
            content=lesson,
            metadata=context,
            importance=importance
        )

    def get_learnings(self, limit: int = 20) -> List[MemoryEntry]:
        """Get past learnings."""
        return self.recall(category="learning", limit=limit, min_importance=0.5)

    def prune_old_memories(self, days: int = 30, min_importance: float = 0.3) -> int:
        """Remove old, low-importance memories."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = datetime.now().isoformat()[:10]  # Just date part
        # Subtract days (simplified)

        cursor.execute("""
            DELETE FROM memories
            WHERE importance < ?
            AND date(timestamp) < date('now', ?)
            AND category NOT IN ('learning', 'resume')
        """, (min_importance, f"-{days} days"))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"Pruned {deleted} old memories")
        return deleted

    def get_statistics(self) -> Dict[str, Any]:
        """Get memory statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM memories")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT category, COUNT(*) FROM memories GROUP BY category")
        by_category = dict(cursor.fetchall())

        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM memories")
        row = cursor.fetchone()
        oldest = row[0]
        newest = row[1]

        conn.close()

        return {
            "total_memories": total,
            "by_category": by_category,
            "oldest": oldest,
            "newest": newest
        }


class SessionContext:
    """
    Tracks current session state for resume capability.

    Engineer0 saves this periodically so she can resume
    exactly where she left off after any restart.
    """

    def __init__(self, memory: PersistentMemory):
        self.memory = memory
        self._context: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load context from memory."""
        state = self.memory.get_resume_state()
        self._context = state.get("session_context", {})

    def set(self, key: str, value: Any) -> None:
        """Set a context value."""
        self._context[key] = value
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a context value."""
        return self._context.get(key, default)

    def _save(self) -> None:
        """Save context to memory."""
        self.memory.save_resume_state(session_context=self._context)

    def checkpoint(
        self,
        goal_id: Optional[str] = None,
        task_id: Optional[str] = None,
        pending_actions: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """Save a checkpoint for resume."""
        self.memory.save_resume_state(
            current_goal_id=goal_id,
            current_task_id=task_id,
            session_context=self._context,
            pending_actions=pending_actions
        )

    def get_checkpoint(self) -> Dict[str, Any]:
        """Get the last checkpoint."""
        return self.memory.get_resume_state()

    def clear(self) -> None:
        """Clear the checkpoint after successful resume."""
        self.memory.clear_resume_state()
        self._context = {}
