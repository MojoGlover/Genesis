"""
agent/core/startup.py — First-boot orchestration hooks.

Runs extra one-time setup that should happen before an agent goes live for
the first time, gated behind FIRST_BOOT=true (default false — existing
agents are unaffected by anything in here). Called from main.py right after
module clients are built (mods) and the mission is loaded, before the graph
is built, so a filed capability_request or a drafted personality.yaml can
still influence what gets built.

Currently one hook: self-spec (agent/bootstrap/self_spec.py) — gap detection
+ personality draft. Add further first-boot-only steps here, not in main.py.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def is_first_boot() -> bool:
    return os.environ.get("FIRST_BOOT", "").strip().lower() in ("1", "true", "yes")


def run_first_boot_hooks(
    agent_id: str,
    agent_dir: Path,
    missions_dir: Path,
    mods: Any,
    plugops_url: str,
) -> dict[str, Any] | None:
    """Run first-boot-only setup. No-op (returns None) unless FIRST_BOOT=true.
    Never raises — a first-boot hook failing must not block a real boot."""
    if not is_first_boot():
        return None

    logger.info(f"[startup] FIRST_BOOT=true — running self-spec for {agent_id}")
    try:
        from agent.bootstrap.self_spec import run_self_spec

        mission_path = missions_dir / f"{agent_id.upper()}.mission.txt"
        result = run_self_spec(
            mission_path=mission_path,
            tool_bus=mods.tool_bus,
            plugops_url=plugops_url,
            agent_id=agent_id,
            identity_dir=agent_dir / "identity",
        )
        logger.info(f"[startup] self-spec result: {result}")
        return result
    except Exception as e:
        logger.error(f"[startup] self-spec hook failed: {e}")
        return {"gaps_found": [], "requests_filed": [], "personality_written": False, "error": str(e)}
