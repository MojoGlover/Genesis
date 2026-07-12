"""
task_queue.py — Persistent task queue for Engineer0's autonomous loop.

Zee checks this every check_interval_seconds. Any OPEN task gets picked up,
run through the full ReAct graph, and marked DONE or FAILED.

Schema:
    ~/.engineer0/tasks.db → tasks table

Task lifecycle:
    open → in_progress → done
                      → failed (with error)

API:
    add_task(title, description, priority=5, source="human") → task_id
    next_open_task() → task dict or None
    mark_in_progress(task_id)
    mark_done(task_id, result)
    mark_failed(task_id, error)
    list_tasks(status=None, limit=20) → list of task dicts
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT UNIQUE NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    priority     INTEGER DEFAULT 5,
    status       TEXT DEFAULT 'open',
    source       TEXT DEFAULT 'human',
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    result       TEXT,
    error        TEXT
)
"""


def _conn(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "tasks.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def add_task(
    data_dir: Path,
    title: str,
    description: str,
    priority: int = 5,
    source: str = "human",
) -> str:
    """Queue a new task. Returns task_id."""
    task_id = str(uuid.uuid4())[:8]
    conn = _conn(data_dir)
    conn.execute(
        """INSERT INTO tasks (task_id, title, description, priority, status, source, created_at)
           VALUES (?, ?, ?, ?, 'open', ?, ?)""",
        (task_id, title, description, priority, source, _now()),
    )
    conn.commit()
    conn.close()
    return task_id


def next_open_task(data_dir: Path) -> dict | None:
    """Return the highest-priority open task, or None."""
    conn = _conn(data_dir)
    row = conn.execute(
        "SELECT * FROM tasks WHERE status = 'open' ORDER BY priority DESC, id ASC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_in_progress(data_dir: Path, task_id: str) -> None:
    conn = _conn(data_dir)
    conn.execute(
        "UPDATE tasks SET status='in_progress', started_at=? WHERE task_id=?",
        (_now(), task_id),
    )
    conn.commit()
    conn.close()


def mark_done(data_dir: Path, task_id: str, result: str) -> None:
    conn = _conn(data_dir)
    conn.execute(
        "UPDATE tasks SET status='done', completed_at=?, result=? WHERE task_id=?",
        (_now(), result[:4000], task_id),
    )
    conn.commit()
    conn.close()


def mark_failed(data_dir: Path, task_id: str, error: str) -> None:
    conn = _conn(data_dir)
    conn.execute(
        "UPDATE tasks SET status='failed', completed_at=?, error=? WHERE task_id=?",
        (_now(), str(error)[:2000], task_id),
    )
    conn.commit()
    conn.close()


def list_tasks(data_dir: Path, status: str | None = None, limit: int = 20) -> list[dict]:
    conn = _conn(data_dir)
    if status:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task(data_dir: Path, task_id: str) -> dict | None:
    conn = _conn(data_dir)
    row = conn.execute(
        "SELECT * FROM tasks WHERE task_id=?", (task_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
