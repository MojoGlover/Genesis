"""
Engineer0 Task Queue

Priority queue with multi-step goals, retry logic, and dependency tracking.
"""

from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import heapq


class TaskPriority(Enum):
    """Task priority levels."""
    CRITICAL = 0  # Immediate attention
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    BACKGROUND = 4


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    BLOCKED = "blocked"  # Waiting on dependencies


class TaskComplexity(Enum):
    """Task complexity for routing."""
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    RESEARCH = "research"


@dataclass
class Task:
    """A single task in the queue."""
    description: str
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    priority: TaskPriority = TaskPriority.MEDIUM
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    status: TaskStatus = TaskStatus.PENDING

    # Execution tracking
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Retry logic
    retries: int = 0
    max_retries: int = 3
    retry_after: Optional[float] = None
    last_error: Optional[str] = None

    # Goal/dependency tracking
    goal_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)

    # Routing hints
    force_provider: Optional[str] = None  # Force specific provider
    data: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None

    def __lt__(self, other: Task) -> bool:
        """Compare for priority queue (lower priority value = higher priority)."""
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        return self.created_at < other.created_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["priority"] = self.priority.value
        d["complexity"] = self.complexity.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Task:
        """Create from dictionary."""
        d["priority"] = TaskPriority(d["priority"])
        d["complexity"] = TaskComplexity(d["complexity"])
        d["status"] = TaskStatus(d["status"])
        return cls(**d)

    def can_run(self, completed_tasks: set) -> bool:
        """Check if this task can run (dependencies satisfied)."""
        if self.status != TaskStatus.PENDING and self.status != TaskStatus.RETRY_SCHEDULED:
            return False
        if self.retry_after and time.time() < self.retry_after:
            return False
        for dep in self.dependencies:
            if dep not in completed_tasks:
                return False
        return True


@dataclass
class Goal:
    """A multi-step goal broken into tasks."""
    description: str
    goal_id: str = field(default_factory=lambda: f"goal_{uuid.uuid4().hex[:8]}")
    priority: TaskPriority = TaskPriority.MEDIUM

    # Tracking
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    task_ids: List[str] = field(default_factory=list)

    # Metrics
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_retries: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Goal:
        d["priority"] = TaskPriority(d["priority"])
        return cls(**d)


class TaskQueue:
    """
    Priority queue with goals, dependencies, and retry logic.

    Features:
    - Priority ordering (CRITICAL > HIGH > MEDIUM > LOW > BACKGROUND)
    - Multi-step goals with task dependencies
    - Retry with exponential backoff
    - Persistent state
    """

    def __init__(self, persist_path: Optional[Path] = None):
        self.persist_path = persist_path
        self._heap: List[Task] = []
        self._tasks: Dict[str, Task] = {}
        self._goals: Dict[str, Goal] = {}
        self._completed: set = set()

        if persist_path and persist_path.exists():
            self._load()

    def add_task(self, task: Task) -> str:
        """Add a task to the queue."""
        self._tasks[task.task_id] = task
        task.status = TaskStatus.QUEUED
        heapq.heappush(self._heap, task)
        self._persist()
        return task.task_id

    def add_tasks(self, tasks: List[Task]) -> List[str]:
        """Add multiple tasks."""
        return [self.add_task(t) for t in tasks]

    def create_goal(
        self,
        description: str,
        steps: List[Dict[str, Any]],
        priority: TaskPriority = TaskPriority.MEDIUM
    ) -> str:
        """
        Create a multi-step goal.

        Args:
            description: Goal description
            steps: List of step definitions:
                   [{"description": "...", "complexity": "simple", "depends_on": [0, 1]}]
                   depends_on uses step indices
            priority: Goal priority (applied to all tasks)

        Returns:
            goal_id
        """
        goal = Goal(description=description, priority=priority)
        task_ids = []

        for i, step in enumerate(steps):
            # Resolve dependencies (step indices → task_ids)
            deps = []
            for dep_idx in step.get("depends_on", []):
                if dep_idx < len(task_ids):
                    deps.append(task_ids[dep_idx])

            task = Task(
                description=step.get("description", f"Step {i+1}"),
                priority=priority,
                complexity=TaskComplexity(step.get("complexity", "medium")),
                goal_id=goal.goal_id,
                dependencies=deps,
                max_retries=step.get("max_retries", 3),
                force_provider=step.get("force_provider"),
                data=step.get("data", {}),
            )

            self.add_task(task)
            task_ids.append(task.task_id)

        goal.task_ids = task_ids
        self._goals[goal.goal_id] = goal
        self._persist()

        return goal.goal_id

    def get_next_task(self) -> Optional[Task]:
        """Get the next runnable task (highest priority, dependencies satisfied)."""
        # Rebuild heap with current tasks (some may have changed status)
        runnable = []

        for task in self._tasks.values():
            if task.can_run(self._completed):
                runnable.append(task)

        if not runnable:
            return None

        # Sort by priority then creation time
        runnable.sort()
        task = runnable[0]
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self._persist()

        return task

    def complete_task(self, task_id: str, result: Any = None) -> None:
        """Mark a task as completed."""
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        task.result = result
        self._completed.add(task_id)

        # Update goal if part of one
        if task.goal_id and task.goal_id in self._goals:
            goal = self._goals[task.goal_id]
            goal.tasks_completed += 1
            self._check_goal_completion(goal)

        self._persist()

    def fail_task(
        self,
        task_id: str,
        error: str,
        backoff_base: float = 2.0
    ) -> bool:
        """
        Mark a task as failed. Schedules retry if retries remaining.

        Returns:
            True if retry scheduled, False if permanently failed
        """
        if task_id not in self._tasks:
            return False

        task = self._tasks[task_id]
        task.last_error = error

        # Update goal metrics
        if task.goal_id and task.goal_id in self._goals:
            goal = self._goals[task.goal_id]
            goal.total_retries += 1

        if task.retries < task.max_retries:
            task.retries += 1
            delay = min(backoff_base ** task.retries, 300)  # Cap at 5 min
            task.retry_after = time.time() + delay
            task.status = TaskStatus.RETRY_SCHEDULED
            self._persist()
            return True
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()

            if task.goal_id and task.goal_id in self._goals:
                goal = self._goals[task.goal_id]
                goal.tasks_failed += 1

            self._persist()
            return False

    def _check_goal_completion(self, goal: Goal) -> bool:
        """Check if a goal is complete."""
        all_done = all(
            self._tasks[tid].status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            for tid in goal.task_ids
            if tid in self._tasks
        )

        if all_done and goal.completed_at is None:
            goal.completed_at = time.time()
            return True
        return False

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        """Get a goal by ID."""
        return self._goals.get(goal_id)

    def get_pending_count(self) -> int:
        """Get count of pending/queued tasks."""
        return sum(
            1 for t in self._tasks.values()
            if t.status in [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RETRY_SCHEDULED]
        )

    def get_running_count(self) -> int:
        """Get count of running tasks."""
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)

    def has_work(self) -> bool:
        """Check if there's any pending work."""
        return any(t.can_run(self._completed) for t in self._tasks.values())

    def get_statistics(self) -> Dict[str, Any]:
        """Get queue statistics."""
        tasks_by_status = {}
        for status in TaskStatus:
            tasks_by_status[status.value] = sum(
                1 for t in self._tasks.values() if t.status == status
            )

        goals_completed = sum(1 for g in self._goals.values() if g.completed_at)
        goals_pending = len(self._goals) - goals_completed

        return {
            "total_tasks": len(self._tasks),
            "tasks_by_status": tasks_by_status,
            "total_goals": len(self._goals),
            "goals_completed": goals_completed,
            "goals_pending": goals_pending,
            "total_retries": sum(t.retries for t in self._tasks.values()),
        }

    def _persist(self) -> None:
        """Save state to disk."""
        if not self.persist_path:
            return

        data = {
            "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
            "goals": {gid: g.to_dict() for gid, g in self._goals.items()},
            "completed": list(self._completed),
        }

        self.persist_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        """Load state from disk."""
        if not self.persist_path or not self.persist_path.exists():
            return

        try:
            data = json.loads(self.persist_path.read_text())

            self._tasks = {
                tid: Task.from_dict(t) for tid, t in data.get("tasks", {}).items()
            }
            self._goals = {
                gid: Goal.from_dict(g) for gid, g in data.get("goals", {}).items()
            }
            self._completed = set(data.get("completed", []))

            # Rebuild heap
            self._heap = list(self._tasks.values())
            heapq.heapify(self._heap)

        except Exception:
            pass  # Start fresh if load fails

    def clear_completed(self, older_than_hours: float = 24) -> int:
        """Remove completed/failed tasks older than threshold."""
        cutoff = time.time() - (older_than_hours * 3600)
        removed = 0

        for tid in list(self._tasks.keys()):
            task = self._tasks[tid]
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                if task.completed_at and task.completed_at < cutoff:
                    del self._tasks[tid]
                    self._completed.discard(tid)
                    removed += 1

        self._persist()
        return removed
