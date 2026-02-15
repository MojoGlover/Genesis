"""SQLite-based persistent memory with FTS5 search."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ai_starter.memory.schemas import MemoryCategory, MemoryItem


class MemoryStore:
    """SQLite memory storage with full-text search."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables and FTS5 index."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                content=memories,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.rowid;
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                UPDATE memories_fts SET content = new.content WHERE rowid = new.rowid;
            END;
        """)
        self.conn.commit()

    def store(self, item: MemoryItem) -> None:
        """Insert a memory item."""
        self.conn.execute(
            """
            INSERT INTO memories (id, category, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.category.value,
                item.content,
                json.dumps(item.metadata),
                item.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_recent(
        self, limit: int = 10, category: MemoryCategory | None = None
    ) -> list[MemoryItem]:
        """Fetch recent memories, optionally filtered by category."""
        query = "SELECT * FROM memories"
        params: tuple = ()
        if category:
            query += " WHERE category = ?"
            params = (category.value,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params = (*params, limit)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_item(row) for row in rows]

    def search(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Full-text search across memory content."""
        rows = self.conn.execute(
            """
            SELECT m.*
            FROM memories m
            JOIN memories_fts f ON m.rowid = f.rowid
            WHERE memories_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def count(self) -> int:
        """Total number of stored memories."""
        row = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0

    def cleanup(self, older_than_days: int = 90) -> int:
        """Remove old memories. Returns count deleted."""
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        cursor = self.conn.execute(
            "DELETE FROM memories WHERE created_at < ?",
            (cutoff.isoformat(),),
        )
        self.conn.commit()
        return cursor.rowcount

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        """Convert DB row to MemoryItem."""
        return MemoryItem(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            content=row["content"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
