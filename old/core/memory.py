from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

# BASE_DIR = project root (flask_test)
BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "memory.db"


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory (
            id TEXT PRIMARY KEY,
            ts REAL,
            type TEXT,
            payload TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def log_memory(entry_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    rec = {
        "id": str(uuid.uuid4()),
        "ts": time.time(),
        "type": entry_type,
        "payload": json.dumps(payload, ensure_ascii=False),
    }

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memory (id, ts, type, payload) VALUES (?, ?, ?, ?)",
        (rec["id"], rec["ts"], rec["type"], rec["payload"]),
    )
    conn.commit()
    conn.close()

    return rec


def read_memory(limit: int = 50) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ts, type, payload FROM memory ORDER BY ts DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()

    items: List[Dict[str, Any]] = []
    for rid, ts_val, rtype, payload in rows:
        items.append(
            {
                "id": rid,
                "ts": ts_val,
                "type": rtype,
                "payload": json.loads(payload),
            }
        )
    return items
