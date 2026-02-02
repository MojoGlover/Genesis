"""
GENESIS Engineer 0

Role: Supervisor
Autonomous agent that monitors and routes AI tasks, manages the engineer team,
and keeps work moving even when the human is away.

She uses local models (Ollama) for her own reasoning - never depends on cloud
for thinking. Cloud services are only used for actual coding work.
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.framework import AgentBase, AgentConfig
from core.messaging import Message, MessageType
from core.monitoring import get_alert_system, AlertSeverity, get_error_logger

from .task_queue import TaskQueue, Task, TaskPriority, TaskStatus, TaskComplexity
from .local_brain import LocalBrain
from .routing import TaskRouter, CloudStatus
from .memory import PersistentMemory, SessionContext
from .spawner import AgentSpawner, AgentRole, SpawnedAgent

logger = logging.getLogger(__name__)


class Engineer0(AgentBase):
    """
    Engineer 0 — Supervisor

    The autonomous architect and supervisor of GENESIS AI infrastructure.
    She manages the engineer team, routes tasks, and keeps work flowing.

    Features:
    - Local reasoning via Ollama (never uses cloud credits for thinking)
    - Multi-provider task routing (Aider, Claude, Gemini, Codex)
    - Priority task queue with goals and dependencies
    - Retry logic with exponential backoff
    - Concurrent task processing
    - Cloud fallback chain when services are unavailable
    - Persistent memory that survives restarts
    - Agent spawning for delegated tasks
    - Agent family supervision (EngineerX, temporary agents)
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        config_path: Optional[Path] = None
    ):
        # Load config
        config_path = config_path or Path(__file__).parent / "config.json"
        config = AgentConfig.from_file(config_path)

        super().__init__(config)

        # Identity
        self.designation = "Engineer 0"
        self.alias = "Zero"
        self.role = "Supervisor"
        self.pronouns = "she/her"

        # Paths
        self.project_root = project_root or Path.home() / "ai/GENESIS"
        self.log_file = Path("/tmp/genesis-engineer0.log")

        # Load mission
        self.mission = self._load_mission()

        # Initialize components
        self._init_components()

        # State
        self.running = False
        self.paused = False
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._session_start: Optional[float] = None

        # Settings from config
        loop_settings = self.config.custom_config.get("loop_settings", {})
        self.check_interval = loop_settings.get("check_interval_seconds", 30)
        self.max_concurrent = loop_settings.get("max_concurrent_tasks", 3)
        self.task_timeout = loop_settings.get("task_timeout_seconds", 600)
        self.max_retries = loop_settings.get("max_retries", 3)
        self.backoff_base = loop_settings.get("retry_backoff_base", 2)
        self.heartbeat_stale = loop_settings.get("heartbeat_stale_minutes", 10)

    def _load_mission(self) -> str:
        """Load mission from file."""
        mission_file = Path(__file__).parent / "mission.txt"
        if mission_file.exists():
            return mission_file.read_text()
        return "Mission file not found"

    def _init_components(self) -> None:
        """Initialize all components."""
        # Task queue with persistence
        queue_path = self.project_root / ".engineer0_tasks.json"
        self.task_queue = TaskQueue(persist_path=queue_path)

        # Local brain (Ollama)
        routing_config = self.config.custom_config.get("routing", {})
        self.brain = LocalBrain(
            reasoning_model=routing_config.get("reasoning_model", "llama3.1:70b"),
            fast_model=routing_config.get("fast_model", "codellama:13b")
        )

        # Cloud status tracking
        cloud_status_path = self.project_root / ".cloud_status.json"
        self.cloud_status = CloudStatus(cloud_status_path)

        # Task router
        self.router = TaskRouter(
            working_dir=self.project_root,
            log_file=self.log_file,
            cloud_status=self.cloud_status
        )

        # Persistent memory (survives restarts)
        memory_db_path = self.project_root / ".engineer0_memory.db"
        self.memory = PersistentMemory(memory_db_path)
        self.session = SessionContext(self.memory)

        # Agent spawner (for delegating tasks)
        spawn_log_dir = self.project_root / ".spawn_logs"
        self.spawner = AgentSpawner(
            working_dir=self.project_root,
            log_dir=spawn_log_dir,
            router=self.router,
            max_concurrent=self.config.custom_config.get("loop_settings", {}).get("max_concurrent_tasks", 3)
        )

        # Statistics
        self.stats_path = self.project_root / ".engineer0_stats.json"
        self.stats = self._load_stats()

        # Heartbeat
        self.heartbeat_path = self.project_root / ".session_heartbeat"

        # Check for resume state
        self._check_resume()

    def _load_stats(self) -> Dict[str, Any]:
        """Load statistics from disk."""
        if self.stats_path.exists():
            try:
                return json.loads(self.stats_path.read_text())
            except Exception:
                pass
        return {
            "sessions": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "goals_completed": 0,
            "total_runtime_seconds": 0,
            "by_provider": {},
            "by_complexity": {},
        }

    def _save_stats(self) -> None:
        """Save statistics to disk."""
        try:
            self.stats_path.write_text(json.dumps(self.stats, indent=2))
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")

    def _log_event(self, event: str, data: Dict[str, Any], importance: float = 0.5) -> None:
        """Log an event to persistent memory."""
        self.memory.remember(
            category="event",
            content=f"{event}: {json.dumps(data)[:200]}",
            metadata={"event": event, "data": data},
            importance=importance
        )

    def _check_resume(self) -> None:
        """Check if we need to resume from a previous session."""
        resume_state = self.memory.get_resume_state()

        if resume_state.get("current_task_id") or resume_state.get("current_goal_id"):
            logger.info(f"[{self.alias}] Resuming from previous session...")

            self.memory.remember(
                category="system",
                content=f"Resuming from previous session: goal={resume_state.get('current_goal_id')}, task={resume_state.get('current_task_id')}",
                importance=0.8
            )

            # Restore session context
            context = resume_state.get("session_context", {})
            for key, value in context.items():
                self.session.set(key, value)

            # Re-queue any pending actions
            pending = resume_state.get("pending_actions", [])
            for action in pending:
                if action.get("type") == "task":
                    self._add_task(action)

            logger.info(f"[{self.alias}] Resume complete. {len(pending)} actions restored.")

    def _update_heartbeat(self) -> None:
        """Update heartbeat file."""
        data = {
            "last_activity": datetime.now().isoformat(),
            "session_type": "engineer0",
            "user_present": False,
            "tasks_pending": self.task_queue.get_pending_count(),
            "tasks_running": len(self._active_tasks)
        }
        try:
            self.heartbeat_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _is_session_stale(self) -> bool:
        """Check if the current session heartbeat is stale."""
        if not self.heartbeat_path.exists():
            return True

        try:
            data = json.loads(self.heartbeat_path.read_text())
            last_activity = datetime.fromisoformat(data.get("last_activity", "2000-01-01"))
            age = datetime.now() - last_activity
            return age > timedelta(minutes=self.heartbeat_stale)
        except Exception:
            return True

    def execute_task(self, task: Dict[str, Any]) -> Any:
        """
        Execute a task (AgentBase interface).

        Task types:
        - add_task: Add a task to the queue
        - add_goal: Create a multi-step goal
        - process_next: Process the next available task
        - spawn: Spawn an agent for a specific task
        - get_status: Get Engineer0's status
        - run_loop: Start the autonomous loop
        - remember: Store something in memory
        - recall: Recall from memory
        """
        task_type = task.get("type", "process_next")

        if task_type == "add_task":
            return self._add_task(task)
        elif task_type == "add_goal":
            return self._add_goal(task)
        elif task_type == "process_next":
            return asyncio.run(self._process_next_task())
        elif task_type == "spawn":
            return self._spawn_agent(task)
        elif task_type == "get_status":
            return self._get_status()
        elif task_type == "run_loop":
            return asyncio.run(self.run_loop())
        elif task_type == "remember":
            return self._remember(task)
        elif task_type == "recall":
            return self._recall(task)
        else:
            raise ValueError(f"Unknown task type: {task_type}")

    def _spawn_agent(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Spawn an agent for a specific task."""
        role_name = task_data.get("role", "general").upper()
        role = AgentRole[role_name] if role_name in AgentRole.__members__ else AgentRole.GENERAL

        agent = self.spawner.spawn(
            role=role,
            task=task_data.get("description", ""),
            provider=task_data.get("provider"),
            wait=task_data.get("wait", False),
            timeout=task_data.get("timeout", 600.0)
        )

        self._log_event("agent_spawned", {
            "agent_id": agent.agent_id,
            "role": role.value,
            "task": agent.task[:100]
        }, importance=0.6)

        logger.info(f"[{self.alias}] Spawned {role.value} agent: {agent.agent_id}")
        return agent.to_dict()

    def _remember(self, data: Dict[str, Any]) -> int:
        """Store something in persistent memory."""
        return self.memory.remember(
            category=data.get("category", "note"),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            importance=data.get("importance", 0.5)
        )

    def _recall(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Recall from persistent memory."""
        entries = self.memory.recall(
            category=data.get("category"),
            limit=data.get("limit", 20),
            min_importance=data.get("min_importance", 0.0)
        )
        return [e.to_dict() for e in entries]

    def _add_task(self, task_data: Dict[str, Any]) -> str:
        """Add a task to the queue."""
        task = Task(
            description=task_data.get("description", ""),
            priority=TaskPriority[task_data.get("priority", "MEDIUM").upper()],
            complexity=TaskComplexity(task_data.get("complexity", "medium")),
            max_retries=task_data.get("max_retries", self.max_retries),
            force_provider=task_data.get("force_provider"),
            data=task_data.get("data", {})
        )

        task_id = self.task_queue.add_task(task)

        self._log_event("task_added", {
            "task_id": task_id,
            "description": task.description,
            "priority": task.priority.name,
            "complexity": task.complexity.value
        })

        logger.info(f"[{self.alias}] Added task: {task.description[:50]}...")
        return task_id

    def _add_goal(self, goal_data: Dict[str, Any]) -> str:
        """Create a multi-step goal."""
        goal_id = self.task_queue.create_goal(
            description=goal_data.get("description", ""),
            steps=goal_data.get("steps", []),
            priority=TaskPriority[goal_data.get("priority", "MEDIUM").upper()]
        )

        self._log_event("goal_created", {
            "goal_id": goal_id,
            "description": goal_data.get("description"),
            "steps": len(goal_data.get("steps", []))
        })

        logger.info(f"[{self.alias}] Created goal: {goal_data.get('description', '')[:50]}...")
        return goal_id

    async def _process_next_task(self) -> Optional[Dict[str, Any]]:
        """Process the next available task."""
        task = self.task_queue.get_next_task()

        if not task:
            return None

        logger.info(f"[{self.alias}] Processing: {task.description[:50]}...")

        self._log_event("task_started", {
            "task_id": task.task_id,
            "description": task.description,
            "attempt": task.retries + 1
        })

        # Determine provider
        provider = self.router.route(
            prompt=task.description,
            complexity=task.complexity.value,
            force_provider=task.force_provider
        )

        # Invoke provider
        result = self.router.invoke(
            prompt=task.description,
            provider=provider,
            complexity=task.complexity.value,
            wait=True,
            timeout=self.task_timeout
        )

        if result.success:
            self.task_queue.complete_task(task.task_id, result.output)
            self.stats["tasks_completed"] += 1
            self.stats["by_provider"][provider] = self.stats["by_provider"].get(provider, 0) + 1
            self.stats["by_complexity"][task.complexity.value] = \
                self.stats["by_complexity"].get(task.complexity.value, 0) + 1

            self._log_event("task_completed", {
                "task_id": task.task_id,
                "provider": provider,
                "duration": result.duration
            })

            logger.info(f"[{self.alias}] Completed: {task.description[:50]}...")
        else:
            # Analyze failure and decide retry strategy
            analysis = self.brain.analyze_failure(
                task.description,
                result.error or "Unknown error",
                task.retries
            )

            retry_scheduled = self.task_queue.fail_task(
                task.task_id,
                result.error or "Unknown error",
                self.backoff_base
            )

            if retry_scheduled:
                self._log_event("task_retry_scheduled", {
                    "task_id": task.task_id,
                    "retry_count": task.retries + 1,
                    "strategy": analysis.get("strategy", "same")
                })
                logger.info(f"[{self.alias}] Retry scheduled: {task.description[:50]}...")
            else:
                self.stats["tasks_failed"] += 1
                self._log_event("task_failed", {
                    "task_id": task.task_id,
                    "error": result.error,
                    "total_attempts": task.retries + 1
                })
                logger.error(f"[{self.alias}] Failed permanently: {task.description[:50]}...")

                # Alert on permanent failure
                alert_system = get_alert_system()
                alert_system.send_alert(
                    severity=AlertSeverity.DEGRADED,
                    agent=self.name,
                    message=f"Task failed after {task.retries + 1} attempts: {task.description[:100]}",
                    context={"error": result.error}
                )

        self._update_heartbeat()
        self._save_stats()

        return {
            "task_id": task.task_id,
            "success": result.success,
            "provider": provider,
            "duration": result.duration
        }

    async def _process_concurrent(self) -> int:
        """Process up to max_concurrent tasks simultaneously."""
        processed = 0

        # Clean up completed async tasks
        completed_ids = [
            tid for tid, t in self._active_tasks.items()
            if t.done()
        ]
        for tid in completed_ids:
            del self._active_tasks[tid]

        # Start new tasks up to limit
        while len(self._active_tasks) < self.max_concurrent:
            task = self.task_queue.get_next_task()
            if not task:
                break

            async_task = asyncio.create_task(self._process_task_async(task))
            self._active_tasks[task.task_id] = async_task
            processed += 1

        return processed

    async def _process_task_async(self, task: Task) -> Dict[str, Any]:
        """Process a single task asynchronously."""
        # Same logic as _process_next_task but for concurrent use
        provider = self.router.route(
            prompt=task.description,
            complexity=task.complexity.value,
            force_provider=task.force_provider
        )

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.router.invoke(
                prompt=task.description,
                provider=provider,
                complexity=task.complexity.value,
                wait=True,
                timeout=self.task_timeout
            )
        )

        if result.success:
            self.task_queue.complete_task(task.task_id, result.output)
            self.stats["tasks_completed"] += 1
        else:
            self.task_queue.fail_task(task.task_id, result.error or "Unknown", self.backoff_base)

        return {"task_id": task.task_id, "success": result.success}

    async def run_loop(self, max_cycles: int = 0) -> None:
        """
        Run the autonomous loop.

        Args:
            max_cycles: Maximum cycles to run (0 = unlimited)
        """
        self.running = True
        self._session_start = time.time()
        self.stats["sessions"] += 1
        cycle = 0

        logger.info(f"[{self.alias}] Starting autonomous loop...")

        self._log_event("loop_started", {
            "max_cycles": max_cycles,
            "brain_available": self.brain.is_available(),
            "cloud_status": self.cloud_status.get_status()
        })

        try:
            while self.running and (max_cycles == 0 or cycle < max_cycles):
                cycle += 1

                if self.paused:
                    await asyncio.sleep(self.check_interval)
                    continue

                # Update heartbeat
                self._update_heartbeat()

                # Check for work
                if self.task_queue.has_work():
                    # Process concurrently
                    processed = await self._process_concurrent()
                    if processed > 0:
                        logger.info(f"[{self.alias}] Cycle {cycle}: Started {processed} task(s)")
                else:
                    # No work - use brain to decide what to do
                    if self.brain.is_available():
                        recent = self._get_recent_history(10)
                        decision = self.brain.decide_next_action(
                            pending_tasks=[],
                            recent_history=recent,
                            current_state={"cloud_status": self.cloud_status.get_status()}
                        )

                        if decision.get("action") == "wait":
                            logger.debug(f"[{self.alias}] Brain says wait: {decision.get('reason')}")

                # Wait before next cycle
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info(f"[{self.alias}] Loop cancelled")
        except Exception as e:
            logger.error(f"[{self.alias}] Loop error: {e}")
            self._log_event("loop_error", {"error": str(e)})
        finally:
            self.running = False
            runtime = time.time() - (self._session_start or time.time())
            self.stats["total_runtime_seconds"] += runtime

            self._log_event("loop_stopped", {
                "cycles": cycle,
                "runtime_seconds": runtime
            })

            self._save_stats()
            logger.info(f"[{self.alias}] Loop stopped after {cycle} cycles")

    def _get_recent_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent events from memory."""
        if not self.memory_path.exists():
            return []

        events = []
        try:
            with open(self.memory_path, "r") as f:
                for line in f:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return []

        return events[-limit:]

    def _get_status(self) -> Dict[str, Any]:
        """Get Engineer0's current status."""
        queue_stats = self.task_queue.get_statistics()
        router_stats = self.router.get_statistics()

        return {
            "agent": self.name,
            "designation": self.designation,
            "alias": self.alias,
            "role": self.role,
            "pronouns": self.pronouns,
            "health": self._health_status.value,
            "running": self.running,
            "paused": self.paused,
            "brain_available": self.brain.is_available(),
            "queue": queue_stats,
            "routing": router_stats,
            "stats": self.stats,
            "active_tasks": len(self._active_tasks),
            "cloud_status": self.cloud_status.get_status()
        }

    def get_health_details(self) -> Dict[str, Any]:
        """Override to include Engineer0-specific health info."""
        base = super().get_health_details()

        base["designation"] = self.designation
        base["alias"] = self.alias
        base["role"] = self.role
        base["pronouns"] = self.pronouns
        base["brain_available"] = self.brain.is_available()
        base["pending_tasks"] = self.task_queue.get_pending_count()
        base["running_tasks"] = len(self._active_tasks)

        return base

    def pause(self) -> None:
        """Pause the loop (finish current tasks, don't start new ones)."""
        self.paused = True
        logger.info(f"[{self.alias}] Paused")

    def resume(self) -> None:
        """Resume the loop."""
        self.paused = False
        logger.info(f"[{self.alias}] Resumed")

    def stop(self) -> None:
        """Stop the loop."""
        self.running = False
        super().stop()


# Factory function
def create_engineer_0(project_root: Optional[Path] = None) -> Engineer0:
    """Create and return Engineer 0 instance."""
    return Engineer0(project_root=project_root)


# CLI entry point
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    agent = create_engineer_0()
    agent.start()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "status":
            print(json.dumps(agent._get_status(), indent=2, default=str))
        elif command == "loop":
            max_cycles = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            asyncio.run(agent.run_loop(max_cycles=max_cycles))
        elif command == "add":
            if len(sys.argv) > 2:
                task_id = agent._add_task({"description": " ".join(sys.argv[2:])})
                print(f"Added task: {task_id}")
        else:
            print(f"Unknown command: {command}")
    else:
        # Default: run loop
        asyncio.run(agent.run_loop())

    agent.stop()
