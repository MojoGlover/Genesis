"""
Migration trigger — decides when to move the agent to plugwan and initiates it.

Trigger conditions (ALL must be true to move to plugwan):
  1. Task queue contains a task tagged compute: heavy
  2. plugwan Ollama is reachable
  3. No active user conversation in the last 5 minutes
  4. Agent is currently NOT on plugwan

Return conditions (ANY triggers return to plugfoe):
  1. Task queue is empty
  2. plugwan goes unreachable
  3. Agent has been on plugwan > 4 hours with no active task

Called from the autonomous loop (agent/core/loops.py).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from agent.modules import Modules

logger = logging.getLogger(__name__)

_PLUGWAN_OLLAMA = "http://100.113.209.66:11434"
_PLUGWAN_HOST   = "plugwan"
_PLUGFOE_HOST   = "plugfoe"
_CHECK_INTERVAL = 60          # seconds between trigger checks
_IDLE_THRESHOLD = 5 * 60      # 5 minutes of no conversation = idle
_MAX_PLUGWAN_TIME = 4 * 3600  # 4 hours max on plugwan with no active task


def _current_host() -> str:
    """Return the canonical host name for this machine."""
    hostname = socket.gethostname().lower()
    if "plugwan" in hostname or hostname.startswith("darnie"):
        return _PLUGWAN_HOST
    return _PLUGFOE_HOST


def _plugwan_reachable(timeout: float = 3.0) -> bool:
    """Quick check — is plugwan Ollama responding?"""
    try:
        r = httpx.get(f"{_PLUGWAN_OLLAMA}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


class MigrationTrigger:
    """
    Watches for migration conditions and initiates moves via PlugOps.

    Instantiated once per agent boot; runs as an autonomous loop coroutine.
    """

    def __init__(self, agent_id: str, agent_name: str,
                 plugops_base: str, mods: "Modules") -> None:
        self.agent_id    = agent_id
        self.agent_name  = agent_name
        self.plugops_base = plugops_base.rstrip("/")
        self.mods        = mods
        self._last_msg_ts: float = time.time()   # tracks last conversation turn
        self._plugwan_since: float | None = None  # when we arrived on plugwan

    def record_activity(self) -> None:
        """Call this whenever a user message or response is processed."""
        self._last_msg_ts = time.time()

    def _idle(self) -> bool:
        return (time.time() - self._last_msg_ts) > _IDLE_THRESHOLD

    def _has_heavy_task(self, task_queue: list[dict]) -> bool:
        return any(t.get("compute") == "heavy" for t in task_queue)

    async def _begin_migration(self, target: str) -> bool:
        """POST migration lock to PlugOps and push mind state snapshot."""
        source = _current_host()
        try:
            # 1. Push snapshot so target can restore it
            self.mods.mind_state.push_snapshot(
                session_history=[],   # graph manages this — push empty for now
                task_queue=[],
                working_memory={},
                host=source,
            )

            # 2. Set migration lock
            r = httpx.post(
                f"{self.plugops_base}/api/v1/agents/{self.agent_id}/migrate",
                json={
                    "agent_name":  self.agent_name,
                    "source_node": source,
                    "target_node": target,
                    "ttl_seconds": 300,
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                logger.warning(f"[migration] Lock failed: {r.status_code} {r.text[:100]}")
                return False

            logger.info(f"[migration] Lock set — moving {self.agent_name} to {target}")
            return True

        except Exception as e:
            logger.warning(f"[migration] begin_migration failed: {e}")
            return False

    async def _abort_migration(self) -> None:
        try:
            httpx.delete(
                f"{self.plugops_base}/api/v1/agents/{self.agent_id}/migrate",
                params={"agent_name": self.agent_name},
                timeout=5.0,
            )
        except Exception:
            pass

    async def run(self, task_queue_fn=None) -> None:
        """
        Main loop — runs every _CHECK_INTERVAL seconds.

        task_queue_fn: optional callable returning list[dict] of current tasks.
        If not provided, migration is still evaluated but heavy-task check is skipped.
        """
        logger.info(f"[migration] Trigger loop started on {_current_host()}")

        while True:
            await asyncio.sleep(_CHECK_INTERVAL)
            try:
                current_host = _current_host()
                task_queue   = task_queue_fn() if task_queue_fn else []

                # ── Return to plugfoe if on plugwan and conditions met ─────────
                if current_host == _PLUGWAN_HOST:
                    if self._plugwan_since is None:
                        self._plugwan_since = time.time()

                    no_tasks     = not task_queue
                    unreachable  = not _plugwan_reachable()
                    timed_out    = (
                        not task_queue and
                        (time.time() - self._plugwan_since) > _MAX_PLUGWAN_TIME
                    )

                    if no_tasks or unreachable or timed_out:
                        reason = ("no tasks" if no_tasks
                                  else "unreachable" if unreachable
                                  else "timeout")
                        logger.info(f"[migration] Returning to plugfoe ({reason})")
                        if await self._begin_migration(_PLUGFOE_HOST):
                            # plugfoe-side watcher or launchd will restart us there
                            # For now just log — actual process management is plugwan-watcher's job
                            logger.info("[migration] Return snapshot pushed — plugfoe should restart us")
                        continue

                # ── Move to plugwan if on plugfoe and all conditions met ───────
                if current_host == _PLUGFOE_HOST:
                    self._plugwan_since = None
                    has_heavy   = self._has_heavy_task(task_queue)
                    reachable   = _plugwan_reachable()
                    is_idle     = self._idle()

                    if has_heavy and reachable and is_idle:
                        logger.info(
                            f"[migration] Conditions met — moving to plugwan "
                            f"(heavy task, idle {int(time.time()-self._last_msg_ts)}s, plugwan reachable)"
                        )
                        if await self._begin_migration(_PLUGWAN_HOST):
                            # plugwan-watcher will see this lock and start us there
                            # Our process will be terminated by watchdog after new instance registers
                            logger.info("[migration] Migration initiated — waiting for plugwan boot")
                    else:
                        if not has_heavy:
                            logger.debug("[migration] No heavy tasks — staying on plugfoe")
                        elif not reachable:
                            logger.debug("[migration] plugwan unreachable — staying on plugfoe")
                        elif not is_idle:
                            logger.debug("[migration] Active conversation — staying on plugfoe")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[migration] Check error: {e}")
