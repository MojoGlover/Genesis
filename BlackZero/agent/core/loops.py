"""
loops.py — Autonomous loop types for BlackZero agents.

Each agent can run one or more loops alongside its reactive bridge.
Configure in config.yaml under `autonomy.loops`.

Available loop types:

  task_loop     — checks task queue every N seconds, executes pending tasks
                  via the full ReAct graph. The default autonomous mode.

  monitor_loop  — watches a condition (health endpoint, file, metric) and
                  fires a task when the condition triggers. Good for watchdogs.

  cron_loop     — runs a fixed task on a schedule (daily briefing, nightly
                  scan, weekly report). Cron-style string or interval.

  heartbeat_loop — fires a lightweight check every N seconds, logs status,
                   alerts if something is wrong. Lighter than task_loop.

Usage in config.yaml:
  autonomy:
    loops:
      - type: task_loop
        interval_seconds: 30
      - type: cron_loop
        interval_seconds: 86400   # daily
        task: "Run daily health report and send to PlugOps"
      - type: monitor_loop
        interval_seconds: 60
        watch: "http://localhost:5001/health"
        condition: "status != ok"
        task: "Health check failed — investigate and fix"

All loops share the same graph instance and data_dir.
"""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Task loop ─────────────────────────────────────────────────────────────────

async def task_loop(graph, data_dir: Path, interval: int = 30) -> None:
    """
    Check the task queue every `interval` seconds.
    Pick up the next OPEN task and run it through the ReAct graph.
    """
    from agent.core.task_queue import (
        next_open_task, mark_in_progress, mark_done, mark_failed
    )

    logger.info(f"[task_loop] Started (interval={interval}s)")
    task = None
    while True:
        await asyncio.sleep(interval)
        try:
            task = next_open_task(data_dir)
            if not task:
                continue

            logger.info(f"[task_loop] Executing task {task['task_id']}: {task['title']}")
            mark_in_progress(data_dir, task["task_id"])

            prompt = f"TASK [{task['task_id']}]: {task['title']}\n\n{task['description']}"
            state = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: graph.invoke({
                    "message": prompt,
                    "session_id": f"task-{task['task_id']}",
                    "max_iterations": 20,
                })
            )
            result = state.get("response", "No response")
            mark_done(data_dir, task["task_id"], result)
            logger.info(f"[task_loop] Task {task['task_id']} DONE")

        except Exception as e:
            logger.error(f"[task_loop] Error: {e}")
            if task:
                mark_failed(data_dir, task["task_id"], str(e))
            task = None


# ── Monitor loop ──────────────────────────────────────────────────────────────

async def monitor_loop(
    graph,
    data_dir: Path,
    watch_url: str,
    condition: str,
    task_description: str,
    interval: int = 60,
) -> None:
    """
    Poll `watch_url` every `interval` seconds.
    If response doesn't contain expected `condition` value, queue a task.
    condition format: "key=value" e.g. "status=ok"
    """
    from agent.core.task_queue import add_task

    logger.info(f"[monitor_loop] Watching {watch_url} every {interval}s")
    while True:
        await asyncio.sleep(interval)
        try:
            req = urllib.request.Request(watch_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()

            # Simple condition check: "key=value" or "key!=value"
            triggered = False
            if "!=" in condition:
                key, val = condition.split("!=", 1)
                import json
                data = json.loads(body)
                triggered = str(data.get(key.strip(), "")) != val.strip()
            elif "=" in condition:
                key, val = condition.split("=", 1)
                import json
                data = json.loads(body)
                triggered = str(data.get(key.strip(), "")) != val.strip()

            if triggered:
                logger.warning(f"[monitor_loop] Condition triggered: {condition}")
                add_task(
                    data_dir,
                    title=f"Monitor alert: {condition}",
                    description=f"Watch URL: {watch_url}\nCondition triggered: {condition}\n\n{task_description}",
                    priority=8,
                    source="monitor_loop",
                )

        except Exception as e:
            logger.error(f"[monitor_loop] Error checking {watch_url}: {e}")


# ── Cron loop ─────────────────────────────────────────────────────────────────

async def cron_loop(
    graph,
    data_dir: Path,
    task_title: str,
    task_description: str,
    interval: int = 86400,
) -> None:
    """
    Queue a fixed task every `interval` seconds.
    Default: once per day (86400s).
    """
    from agent.core.task_queue import add_task

    logger.info(f"[cron_loop] Scheduled '{task_title}' every {interval}s")
    while True:
        await asyncio.sleep(interval)
        try:
            task_id = add_task(
                data_dir,
                title=task_title,
                description=task_description,
                priority=5,
                source="cron_loop",
            )
            logger.info(f"[cron_loop] Queued scheduled task {task_id}: {task_title}")
        except Exception as e:
            logger.error(f"[cron_loop] Error queuing task: {e}")


# ── Heartbeat loop ────────────────────────────────────────────────────────────

async def heartbeat_loop(
    data_dir: Path,
    agent_name: str,
    interval: int = 60,
) -> None:
    """
    Lightweight status log every `interval` seconds.
    Logs task queue stats. No graph invocation.
    """
    from agent.core.task_queue import list_tasks

    logger.info(f"[heartbeat_loop] Started (interval={interval}s)")
    while True:
        await asyncio.sleep(interval)
        try:
            open_tasks  = list_tasks(data_dir, status="open", limit=100)
            active      = list_tasks(data_dir, status="in_progress", limit=10)
            done        = list_tasks(data_dir, status="done", limit=100)
            failed      = list_tasks(data_dir, status="failed", limit=100)
            logger.info(
                f"[{agent_name}] tasks — open:{len(open_tasks)} "
                f"active:{len(active)} done:{len(done)} failed:{len(failed)}"
            )
        except Exception as e:
            logger.error(f"[heartbeat_loop] Error: {e}")


# ── Loop builder ──────────────────────────────────────────────────────────────

def build_loops(config: dict, graph, data_dir: Path, agent_name: str) -> list:
    """
    Read config.yaml autonomy.loops and return a list of coroutines to
    pass into asyncio.gather().

    If no autonomy config exists, defaults to task_loop + heartbeat_loop.
    """
    autonomy = config.get("autonomy", {})
    loop_configs = autonomy.get("loops", [])

    # Default: task_loop + heartbeat if nothing configured
    if not loop_configs:
        logger.info("[loops] No autonomy config — using defaults: task_loop + heartbeat_loop")
        return [
            task_loop(graph, data_dir, interval=30),
            heartbeat_loop(data_dir, agent_name, interval=60),
        ]

    coroutines = []
    for lc in loop_configs:
        loop_type = lc.get("type", "task_loop")
        interval  = lc.get("interval_seconds", 30)

        if loop_type == "task_loop":
            coroutines.append(task_loop(graph, data_dir, interval=interval))
            logger.info(f"[loops] task_loop ({interval}s)")

        elif loop_type == "heartbeat_loop":
            coroutines.append(heartbeat_loop(data_dir, agent_name, interval=interval))
            logger.info(f"[loops] heartbeat_loop ({interval}s)")

        elif loop_type == "monitor_loop":
            coroutines.append(monitor_loop(
                graph, data_dir,
                watch_url=lc.get("watch", "http://localhost:5001/health"),
                condition=lc.get("condition", "status!=ok"),
                task_description=lc.get("task", "Investigate the triggered condition."),
                interval=interval,
            ))
            logger.info(f"[loops] monitor_loop → {lc.get('watch')} ({interval}s)")

        elif loop_type == "cron_loop":
            coroutines.append(cron_loop(
                graph, data_dir,
                task_title=lc.get("title", "Scheduled task"),
                task_description=lc.get("task", "Run your scheduled work."),
                interval=interval,
            ))
            logger.info(f"[loops] cron_loop '{lc.get('title')}' ({interval}s)")

        else:
            logger.warning(f"[loops] Unknown loop type: {loop_type} — skipping")

    return coroutines
