"""
memory — SQLite memory module.

Wires SQLiteMemoryManager into the loader's memory_manager slot.
Works locally (data_dir from config) and in Docker (DATA_DIR env var).

Config keys:
    data_dir — base directory for all persistent storage

Environment:
    DATA_DIR — overrides config data_dir (Docker-friendly, takes priority)

Returns:
    {"memory_manager": SQLiteMemoryManager}
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def setup(config: dict) -> dict:
    from memory.sqlite_memory_manager import SQLiteMemoryManager

    # DATA_DIR env var wins (Docker volume mount).
    # Fall back to config, then ~/.{agent_slug}/
    identity  = config.get("identity", {})
    slug      = identity.get("designation", "agent").lower().replace(" ", "")
    default   = f"~/.{slug}"

    data_dir = os.environ.get("DATA_DIR") or config.get("data_dir", default)
    data_dir = Path(data_dir).expanduser()

    manager = SQLiteMemoryManager(data_dir)

    stats = manager.stats()
    logger.info(
        f"Memory module ready: {data_dir}/memory.db "
        f"({stats['total']} entries, avg_importance={stats['avg_importance']})"
    )

    return {"memory_manager": manager}
