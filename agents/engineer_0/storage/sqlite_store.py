# sqlite_store.py
# SQLITE STORAGE ADAPTER
#
# Responsibility:
#   Handles all SQLite-based persistence for this agent.
#
# What does NOT belong here:
#   - Vector/embedding storage (that belongs in vector_store.py)
#   - Memory business logic (that belongs in memory/)
#   - Loose .db files — database files must be gitignored or in a controlled subfolder

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SQLiteStore(ABC):
    """
    Abstract base class for SQLite-backed persistence.

    Concrete implementations connect to a specific database file and
    expose CRUD operations used by MemoryManager and Executor.
    Database files (.db) must never be committed — add them to .gitignore.

    Example agent implementation:
        class AgentSQLiteStore(SQLiteStore):
            def connect(self, db_path):
                import sqlite3
                self._conn = sqlite3.connect(db_path)
                self._conn.row_factory = sqlite3.Row
    """

    @abstractmethod
    def connect(self, db_path: str) -> None:
        """
        Open (or create) a SQLite database at the given path.
        Must be called before any other method.
        """

    @abstractmethod
    def execute(self, query: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        """
        Run a SELECT query and return all matching rows as dicts.

        Args:
            query:  SQL SELECT statement with ? placeholders.
            params: Values to substitute for placeholders.

        Returns:
            List of rows, each row a dict keyed by column name.
        """

    @abstractmethod
    def run(self, statement: str, params: tuple | list = ()) -> None:
        """
        Execute a non-SELECT statement (INSERT, UPDATE, DELETE, CREATE).
        Commits automatically on success.
        """

    @abstractmethod
    def insert(self, table: str, data: dict[str, Any]) -> str:
        """
        Insert a row into the named table.

        Args:
            table: Target table name.
            data:  Column-value mapping for the new row.

        Returns:
            The rowid or primary key of the inserted row as a string.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the database connection and release resources."""

    def table_exists(self, table: str) -> bool:
        """Return True if the named table exists in the database."""
        rows = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return len(rows) > 0
