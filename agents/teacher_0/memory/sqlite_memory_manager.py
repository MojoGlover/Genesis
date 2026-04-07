"""
sqlite_memory_manager.py — Concrete SQLite memory implementation.

Stamped into every agent that needs persistent memory.
Works locally (data_dir from config) and in Docker (DATA_DIR env var).

Supports:
- Persistent storage across sessions
- Importance scoring with decay
- Duplicate detection via word-overlap similarity
- TTL-based expiry
- Keyword search with importance weighting
- Context summary for system prompt injection

NOTE: Imports here use non-prefixed paths (memory.*, models.*) because this
file is designed to be stamped into a standalone agent with its root on sys.path.
Do not change to BlackZero.* prefixes.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from memory.memory_manager import MemoryManager
from memory.memory_schema import MemoryRecord, MemorySource

logger = logging.getLogger(__name__)

# Importance defaults by source
_SOURCE_IMPORTANCE: dict[str, float] = {
    MemorySource.USER:      0.85,
    MemorySource.TOOL:      0.70,
    MemorySource.INFERENCE: 0.55,
    MemorySource.EXTERNAL:  0.60,
}

_DECAY_AFTER_DAYS  = 30    # entries older than this start decaying
_DECAY_RATE        = 0.04  # importance lost per week after decay threshold
_REINFORCE_DELTA   = 0.03  # importance gained per access
_MAX_ENTRIES       = 500
_SIMILARITY_THRESH = 0.72  # word-overlap threshold for deduplication


class SQLiteMemoryManager(MemoryManager):
    """
    Memory manager backed by SQLite.

    Thread-safe via WAL mode. One connection per instance.
    Works locally (~/.{agent}/) and in Docker (/data/ via volume mount).
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir).expanduser()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "memory.db"
        self._conn: sqlite3.Connection | None = None
        self._connect()

    # ── Connection ─────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=10,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        logger.info(f"SQLiteMemoryManager connected: {self._db_path}")

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id           TEXT PRIMARY KEY,
                content      TEXT NOT NULL,
                source       TEXT NOT NULL DEFAULT 'inference',
                tags         TEXT NOT NULL DEFAULT '[]',
                metadata     TEXT NOT NULL DEFAULT '{}',
                importance   REAL NOT NULL DEFAULT 0.6,
                access_count INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                expires_at   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance DESC);
            CREATE INDEX IF NOT EXISTS idx_created    ON memories(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_source     ON memories(source);
        """)
        self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        rec = MemoryRecord(
            id=row["id"],
            content=row["content"],
            source=MemorySource(row["source"]),
            tags=json.loads(row["tags"]),
            metadata=json.loads(row["metadata"]),
            ttl_seconds=None,
        )
        rec.created_at = datetime.fromisoformat(row["created_at"])
        rec.metadata["_importance"]   = row["importance"]
        rec.metadata["_access_count"] = row["access_count"]
        rec.metadata["_updated_at"]   = row["updated_at"]
        if row["expires_at"]:
            expires = datetime.fromisoformat(row["expires_at"])
            rec.ttl_seconds = int((expires - rec.created_at).total_seconds())
        return rec

    # ── Duplicate detection ────────────────────────────────────────────────────

    @staticmethod
    def _word_similarity(a: str, b: str) -> float:
        words_a = {w for w in a.lower().split() if len(w) > 3}
        words_b = {w for w in b.lower().split() if len(w) > 3}
        if not words_a or not words_b:
            return 0.0
        shared = len(words_a & words_b)
        return shared / max(len(words_a), len(words_b))

    def _find_duplicate(self, content: str, source: MemorySource) -> dict | None:
        rows = self._conn.execute(
            "SELECT id, content, importance, access_count FROM memories WHERE source = ?",
            (source.value,),
        ).fetchall()
        for row in rows:
            if self._word_similarity(content, row["content"]) >= _SIMILARITY_THRESH:
                return dict(row)
        return None

    # ── Decay ─────────────────────────────────────────────────────────────────

    def _decayed_importance(self, importance: float, created_at: str) -> float:
        age_days = (datetime.utcnow() - datetime.fromisoformat(created_at)).days
        if age_days < _DECAY_AFTER_DAYS:
            return importance
        if importance >= 0.85:
            return importance  # high-importance memories don't decay
        weeks_over = (age_days - _DECAY_AFTER_DAYS) / 7
        return max(0.10, importance - weeks_over * _DECAY_RATE)

    # ── MemoryManager interface ────────────────────────────────────────────────

    def add_memory(
        self,
        content: str,
        metadata: dict | None = None,
        source: MemorySource = MemorySource.INFERENCE,
        importance: float | None = None,
        tags: list[str] | None = None,
        ttl_hours: int | None = None,
    ) -> str:
        """Store a new memory. Returns its ID. Deduplicates near-identical content."""
        now = datetime.utcnow().isoformat()
        imp = importance if importance is not None else _SOURCE_IMPORTANCE.get(source, 0.6)

        # Deduplication — boost existing instead of inserting a copy
        dup = self._find_duplicate(content, source)
        if dup:
            new_imp = min(1.0, dup["importance"] + 0.10)
            self._conn.execute(
                "UPDATE memories SET importance=?, access_count=access_count+1, updated_at=? WHERE id=?",
                (new_imp, now, dup["id"]),
            )
            self._conn.commit()
            logger.debug(f"Deduped memory {dup['id']}, importance boosted to {new_imp:.2f}")
            return dup["id"]

        expires_at = None
        if ttl_hours:
            expires_at = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()

        mem_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO memories
               (id, content, source, tags, metadata, importance, access_count,
                created_at, updated_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                mem_id,
                content,
                source.value,
                json.dumps(tags or []),
                json.dumps(metadata or {}),
                imp,
                now,
                now,
                expires_at,
            ),
        )
        self._conn.commit()
        self._prune()
        return mem_id

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return None
        self._conn.execute(
            "UPDATE memories SET access_count=access_count+1, importance=MIN(1.0, importance+?) WHERE id=?",
            (_REINFORCE_DELTA, memory_id),
        )
        self._conn.commit()
        return self._row_to_record(row)

    def search_memory(self, query: str, top_k: int = 10) -> list[MemoryRecord]:
        """Keyword search + importance ranking. Fast and offline-safe."""
        now = datetime.utcnow().isoformat()
        words = [w.lower() for w in query.split() if len(w) > 2]
        if not words:
            return []

        rows = self._conn.execute(
            "SELECT * FROM memories WHERE (expires_at IS NULL OR expires_at > ?) ORDER BY importance DESC LIMIT 200",
            (now,),
        ).fetchall()

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            content_lower = row["content"].lower()
            hits = sum(1 for w in words if w in content_lower)
            if hits > 0:
                score = (hits / len(words)) * 0.6 + row["importance"] * 0.4
                scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, row in scored[:top_k]:
            record = self._row_to_record(row)
            results.append(record)
            self._conn.execute(
                "UPDATE memories SET access_count=access_count+1 WHERE id=?",
                (row["id"],),
            )
        if results:
            self._conn.commit()
        return results

    def delete_memory(self, memory_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM memories WHERE id = ?", (memory_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def expire_old_memories(self) -> int:
        now = datetime.utcnow().isoformat()
        cursor = self._conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        self._conn.commit()
        count = cursor.rowcount
        if count:
            logger.info(f"Expired {count} memories")
        return count

    def list_all(self) -> list[MemoryRecord]:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY importance DESC"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    # ── Extras ─────────────────────────────────────────────────────────────────

    def get_context_summary(self, agent_name: str = "Agent", limit: int = 12) -> str:
        """
        Build a context block for injection into the system prompt.
        Blends importance + recency. Agent name configures the header.
        """
        now = datetime.utcnow()
        cutoff = now.isoformat()
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE (expires_at IS NULL OR expires_at > ?) ORDER BY importance DESC LIMIT 100",
            (cutoff,),
        ).fetchall()
        if not rows:
            return ""

        recent_cutoff = (now - timedelta(hours=48)).isoformat()

        scored = []
        for row in rows:
            recency_boost = 0.15 if row["updated_at"] > recent_cutoff else 0.0
            score = row["importance"] + recency_boost
            scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        lines = []
        for _, row in scored[:limit]:
            age_h = (now - datetime.fromisoformat(row["updated_at"])).total_seconds() / 3600
            age_label = "just now" if age_h < 1 else f"{int(age_h)}h ago" if age_h < 24 else f"{int(age_h/24)}d ago"
            tags = json.loads(row["tags"])
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"[{row['source']}]{tag_str} {row['content']} ({age_label})")

        return f"{agent_name}'s memory:\n" + "\n".join(lines)

    def remember(
        self,
        content: str,
        source: MemorySource = MemorySource.USER,
        tags: list[str] | None = None,
        importance: float | None = None,
        ttl_hours: int | None = None,
    ) -> str:
        """Convenience alias for add_memory."""
        return self.add_memory(
            content=content,
            source=source,
            tags=tags,
            importance=importance,
            ttl_hours=ttl_hours,
        )

    def recall(self, query: str, top_k: int = 10) -> list[MemoryRecord]:
        """Alias for search_memory."""
        return self.search_memory(query, top_k)

    def stats(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*) as total, AVG(importance) as avg_imp FROM memories"
        ).fetchone()
        by_source = self._conn.execute(
            "SELECT source, COUNT(*) as n FROM memories GROUP BY source"
        ).fetchall()
        return {
            "total": row["total"],
            "avg_importance": round(row["avg_imp"] or 0, 3),
            "by_source": {r["source"]: r["n"] for r in by_source},
            "db_path": str(self._db_path),
        }

    def _prune(self) -> None:
        """Remove lowest-importance entries when over cap."""
        count = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        if count <= _MAX_ENTRIES:
            return
        overflow = count - _MAX_ENTRIES
        self._conn.execute(
            """DELETE FROM memories WHERE id IN (
               SELECT id FROM memories ORDER BY importance ASC LIMIT ?)""",
            (overflow,),
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
