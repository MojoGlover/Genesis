"""State models for agent loop — tasks, queue, results, reflections."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskPriority(str, Enum):
    """Task priority levels."""
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    retry = "retry"


class Task(BaseModel):
    """A single task in the agent queue."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    priority: TaskPriority = TaskPriority.medium
    status: TaskStatus = TaskStatus.pending
    retries: int = 0
    max_retries: int = 3
    created_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = None
    result: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Step(BaseModel):
    """A single execution step in a plan."""
    description: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.pending


class StepResult(BaseModel):
    """Result of executing a single step."""
    success: bool
    output: str
    error: str | None = None
    duration_ms: int


class Reflection(BaseModel):
    """Agent's reflection on task execution."""
    success: bool
    summary: str
    learnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class TickResult(BaseModel):
    """Result of a single agent loop iteration."""
    task: Task
    steps: list[Step]
    reflection: Reflection
    duration_ms: int


class TaskQueue(BaseModel):
    """Priority queue for tasks with persistence."""
    tasks: list[Task] = Field(default_factory=list)
    completed_ids: set[str] = Field(default_factory=set)

    def add(self, task: Task) -> None:
        """Add task to queue, sorted by priority."""
        self.tasks.append(task)
        self._sort()

    def next(self) -> Task | None:
        """Get highest priority pending task."""
        for task in self.tasks:
            if task.status == TaskStatus.pending:
                task.status = TaskStatus.running
                return task
        return None

    def complete(self, task: Task, result: str) -> None:
        """Mark task as completed."""
        task.status = TaskStatus.completed
        task.result = result
        self.completed_ids.add(task.id)

    def fail(self, task: Task, error: str) -> None:
        """Mark task as failed or retry."""
        task.error = error
        task.retries += 1
        if task.retries < task.max_retries:
            task.status = TaskStatus.retry
        else:
            task.status = TaskStatus.failed
            self.completed_ids.add(task.id)

    def _sort(self) -> None:
        """Sort by priority (critical > high > medium > low)."""
        priority_order = {
            TaskPriority.critical: 0,
            TaskPriority.high: 1,
            TaskPriority.medium: 2,
            TaskPriority.low: 3,
        }
        self.tasks.sort(key=lambda t: (priority_order[t.priority], t.created_at))

    def save(self, path: Path) -> None:
        """Persist queue to JSON."""
        data = self.model_dump(mode="json")
        data["completed_ids"] = list(self.completed_ids)  # sets not JSON-serializable
        path.write_text(json.dumps(data, indent=2, default=str))

    @classmethod
    def load(cls, path: Path) -> TaskQueue:
        """Load queue from JSON."""
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        data["completed_ids"] = set(data.get("completed_ids", []))
        return cls(**data)


class AgentState(BaseModel):
    """Serializable snapshot of agent state."""
    queue: TaskQueue
    stats: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)

    def save(self, path: Path) -> None:
        """Save state to JSON."""
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: Path) -> AgentState:
        """Load state from JSON."""
        if not path.exists():
            return cls(queue=TaskQueue())
        return cls.model_validate_json(path.read_text())
