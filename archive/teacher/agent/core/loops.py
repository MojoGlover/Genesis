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
        condition: "status!=ok"
        task: "Health check failed — investigate and fix"

Monitor condition semantics:
  "key!=value"  — trigger when key is NOT equal to value  (alert on deviation)
  "key=value"   — trigger when key IS equal to value      (alert on match)

All loops share the same graph instance and data_dir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Task loop ─────────────────────────────────────────────────────────────────

async def task_loop(graph, data_dir: Path, interval: int = 30) -> None:
    """
    Check the task queue every `interval` seconds.
    Pick up the next OPEN task and run it through the ReAct graph.
    A concurrency lock prevents overlapping executions if a task runs long.
    """
    from agent.core.task_queue import (
        next_open_task, mark_in_progress, mark_done, mark_failed
    )

    logger.info(f"[task_loop] Started (interval={interval}s)")
    executing = asyncio.Lock()
    task = None

    while True:
        await asyncio.sleep(interval)

        if executing.locked():
            logger.debug("[task_loop] Previous task still running — skipping this interval")
            continue

        async with executing:
            try:
                task = next_open_task(data_dir)
                if not task:
                    continue

                logger.info(f"[task_loop] Executing task {task['task_id']}: {task['title']}")
                mark_in_progress(data_dir, task["task_id"])

                task_id = task["task_id"]  # capture before any await
                prompt  = f"TASK [{task_id}]: {task['title']}\n\n{task['description']}"

                loop   = asyncio.get_running_loop()
                state  = await loop.run_in_executor(
                    None,
                    lambda: graph.invoke(
                        {
                            "message":        prompt,
                            "session_id":     f"task-{task_id}",
                            "max_iterations": 20,
                        },
                        config={"configurable": {"thread_id": f"task-{task_id}"}, "recursion_limit": 100},
                    ),
                )
                result     = state.get("response", "No response").strip()
                tools_ran  = state.get("_tools_ran", 0)
                is_failure = "FAILED:" in result.upper()
                done_claim = "DONE:" in result.upper()

                # Explicit FAILED: → accept as failure regardless of tool count.
                # DONE: with zero tools → hallucination → force failure.
                # No tools, no marker → prose without action → failure.
                # Tools ran → accept result (DONE: or not).
                if is_failure:
                    mark_failed(data_dir, task_id, result)
                    logger.info(f"[task_loop] Task {task_id} FAILED (explicit)")
                elif done_claim and not tools_ran:
                    result = (
                        f"FAILED: Model claimed DONE but ran zero tools — hallucinated completion. "
                        f"Raw: {result[:300]}"
                    )
                    mark_failed(data_dir, task_id, result)
                    logger.warning(f"[task_loop] Task {task_id} FAILED (DONE: with no tools)")
                elif not tools_ran:
                    result = (
                        f"FAILED: No tools executed, no completion marker. "
                        f"Model described instead of acting. Raw: {result[:300]}"
                    )
                    mark_failed(data_dir, task_id, result)
                    logger.warning(f"[task_loop] Task {task_id} FAILED (no tool execution)")
                else:
                    mark_done(data_dir, task_id, result)
                    logger.info(f"[task_loop] Task {task_id} DONE")

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
    condition format:
      "key!=value"  — trigger when key is NOT equal to value
      "key=value"   — trigger when key IS equal to value
    """
    from agent.core.task_queue import add_task

    logger.info(f"[monitor_loop] Watching {watch_url} every {interval}s")
    while True:
        await asyncio.sleep(interval)
        try:
            req = urllib.request.Request(watch_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()

            triggered = False
            if "!=" in condition:
                key, val = condition.split("!=", 1)
                data      = json.loads(body)
                triggered = str(data.get(key.strip(), "")) != val.strip()
            elif "=" in condition:
                key, val = condition.split("=", 1)
                data      = json.loads(body)
                triggered = str(data.get(key.strip(), "")) == val.strip()

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
    """Queue a fixed task every `interval` seconds. Default: once per day."""
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
    """Lightweight status log every `interval` seconds. No graph invocation."""
    from agent.core.task_queue import list_tasks

    logger.info(f"[heartbeat_loop] Started (interval={interval}s)")
    while True:
        await asyncio.sleep(interval)
        try:
            open_tasks = list_tasks(data_dir, status="open",        limit=100)
            active     = list_tasks(data_dir, status="in_progress", limit=10)
            done       = list_tasks(data_dir, status="done",        limit=100)
            failed     = list_tasks(data_dir, status="failed",      limit=100)
            logger.info(
                f"[{agent_name}] tasks — open:{len(open_tasks)} "
                f"active:{len(active)} done:{len(done)} failed:{len(failed)}"
            )
        except Exception as e:
            logger.error(f"[heartbeat_loop] Error: {e}")


# ── Todo loop ─────────────────────────────────────────────────────────────────

async def todo_loop(
    graph,
    data_dir: Path,
    todo_file: str,
    sandbox_path: str,
    interval: int = 60,
) -> None:
    """
    Read ~/engineer0-sandbox/TODO.md every `interval` seconds.
    Pick the next unchecked item, work on it in the sandbox, mark done when finished.
    Results are committed to the sandbox git repo if tests pass.
    """
    import re

    todo_path    = Path(todo_file).expanduser()
    sandbox_dir  = Path(sandbox_path).expanduser()
    executing    = asyncio.Lock()

    logger.info(f"[todo_loop] Watching {todo_path} every {interval}s")

    while True:
        await asyncio.sleep(interval)

        if executing.locked():
            continue

        async with executing:
            try:
                if not todo_path.exists():
                    continue

                content = todo_path.read_text()
                lines   = content.splitlines()

                # Find first unchecked item: "- [ ] ..."
                item_idx  = None
                item_text = None
                for i, line in enumerate(lines):
                    m = re.match(r'^- \[ \] (.+)', line)
                    if m:
                        item_idx  = i
                        item_text = m.group(1).strip()
                        break

                if item_idx is None:
                    continue  # nothing to do

                logger.info(f"[todo_loop] Picked up todo item: {item_text[:80]}")

                # Mark in-progress (➡️)
                lines[item_idx] = f"- [➡️] {item_text}"
                todo_path.write_text("\n".join(lines))

                # Prompt structured to leave no narrative escape route.
                # The model must use tools — describing a plan is not acceptable output.
                prompt = (
                    f"EXECUTE THIS TASK NOW. Do not describe what you will do. Do it.\n\n"
                    f"TASK: {item_text}\n\n"
                    f"SANDBOX: {sandbox_dir}\n\n"
                    f"REQUIREMENTS:\n"
                    f"- Use the shell tool or write_file tool immediately on your first response.\n"
                    f"- Do ALL work inside {sandbox_dir}. Never touch production paths.\n"
                    f"- Write code, run it, fix errors until it works.\n"
                    f"- Tasks that require a report: write the file, then read it back to verify it exists.\n"
                    f"- Tasks that require code: write it, run a test, show the output.\n"
                    f"- Your final response must start with DONE: and summarize what was actually produced.\n"
                    f"- If you cannot complete the task after 3 tool attempts, start your response with FAILED: and explain the blocker.\n"
                    f"- A response that only describes plans without using any tools is not acceptable.\n"
                )

                loop_  = asyncio.get_running_loop()
                state  = await loop_.run_in_executor(
                    None,
                    lambda: graph.invoke(
                        {"message": prompt, "session_id": f"todo-{item_idx}", "max_iterations": 30},
                        config={"configurable": {"thread_id": f"todo-{item_idx}"}, "recursion_limit": 150},
                    ),
                )
                result = state.get("response", "No response").strip()

                # Verify completion.
                # _tools_ran is a counter incremented by the tool node and preserved
                # through respond_node — unlike tool_history which used to be cleared.
                # has_marker alone is NOT sufficient — a hallucinating model can output
                # DONE: with zero tool calls.
                tools_ran  = state.get("_tools_ran", 0)
                is_failure = "FAILED:" in result.upper()
                done_claim = "DONE:" in result.upper()

                # Same logic as task_loop:
                # DONE: with zero tools = hallucinated completion.
                # No tools at all = prose-only = failure.
                # FAILED: = accept explicitly.
                # Tools ran = real work happened.
                if not is_failure and done_claim and not tools_ran:
                    logger.warning(
                        f"[todo_loop] Task {item_text[:60]!r} claimed DONE with zero tool calls — "
                        f"hallucinated completion."
                    )
                    result = f"FAILED: Model claimed DONE but ran zero tools. Raw: {result[:300]}"
                    is_failure = True
                elif not is_failure and not tools_ran:
                    logger.warning(
                        f"[todo_loop] Task {item_text[:60]!r} produced no tool calls and no "
                        f"completion marker — marking FAILED to prevent false completion."
                    )
                    result = f"FAILED: No tools were invoked. Model described a plan instead of executing. Raw: {result[:300]}"
                    is_failure = True

                status_mark = "❌" if is_failure else "✅"
                outcome     = "FAILED" if is_failure else "DONE"
                logger.info(f"[todo_loop] Task {outcome}: {item_text[:60]}")

                # Write result back to TODO.md
                content = todo_path.read_text()
                lines   = content.splitlines()
                for i, line in enumerate(lines):
                    if re.match(r'^- \[➡️\] .+', line):
                        lines[i] = f"- [x] {status_mark} {item_text} — {result[:300]}"
                        break
                todo_path.write_text("\n".join(lines))

                # Commit sandbox work (only on success)
                if not is_failure:
                    try:
                        import subprocess
                        subprocess.run(
                            ["git", "-C", str(sandbox_dir), "add", "-A"],
                            capture_output=True, timeout=10,
                        )
                        subprocess.run(
                            ["git", "-C", str(sandbox_dir), "commit",
                             "-m", f"todo: {item_text[:60]}"],
                            capture_output=True, timeout=10,
                        )
                        logger.info("[todo_loop] Sandbox work committed")
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"[todo_loop] Error: {e}")
                # Un-mark in-progress if something crashed
                try:
                    content = todo_path.read_text()
                    content = content.replace(f"- [➡️]", "- [ ]")
                    todo_path.write_text(content)
                except Exception:
                    pass


# ── Loop builder ──────────────────────────────────────────────────────────────

def build_loops(config: dict, graph, data_dir: Path, agent_name: str) -> list:
    """
    Read config.yaml autonomy.loops and return a list of coroutines to
    pass into asyncio.gather().

    If no autonomy config exists, defaults to task_loop + heartbeat_loop.
    """
    autonomy     = config.get("autonomy", {})
    loop_configs = autonomy.get("loops", [])

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

        elif loop_type == "todo_loop":
            sandbox_cfg  = config.get("sandbox", {})
            todo_file    = sandbox_cfg.get("todo_file", "~/engineer0-sandbox/TODO.md")
            sandbox_path = sandbox_cfg.get("path", "~/engineer0-sandbox")
            coroutines.append(todo_loop(
                graph, data_dir,
                todo_file=todo_file,
                sandbox_path=sandbox_path,
                interval=interval,
            ))
            logger.info(f"[loops] todo_loop → {todo_file} ({interval}s)")

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
