"""
task_progress/queue.py
TaskQueue — app-level container.
Manages an ordered list of TaskProgressBar instances.
The app decides how many can run — the queue just tracks order and state.
"""
from __future__ import annotations

from typing import Callable, Optional
from .bar import TaskProgressBar


class TaskQueue:
    def __init__(self) -> None:
        self._tasks: list[TaskProgressBar] = []
        self._id_counter = 0

    # ── Task management ──────────────────────────────────────────────────────

    def add(
        self,
        name: str,
        projected: float,
        poll_fn: Callable[[], float],
        poll_interval_s: float = 1.0,
    ) -> TaskProgressBar:
        """Add a new task to the end of the queue. Returns the bar instance."""
        bar = TaskProgressBar(
            name=name,
            projected=projected,
            poll_fn=poll_fn,
            poll_interval_s=poll_interval_s,
        )
        bar.position = len(self._tasks)
        self._tasks.append(bar)
        self._reindex()
        return bar

    def remove(self, index: int) -> Optional[TaskProgressBar]:
        """Remove task at index. Returns the removed bar or None."""
        if 0 <= index < len(self._tasks):
            bar = self._tasks.pop(index)
            self._reindex()
            return bar
        return None

    def remove_done(self) -> None:
        """Prune all completed tasks from the queue."""
        self._tasks = [t for t in self._tasks if not t._snapshot(0).done]
        self._reindex()

    # ── Reordering ───────────────────────────────────────────────────────────

    def move_up(self, index: int) -> bool:
        """Move task at index one position up. Returns True if moved."""
        if index <= 0 or index >= len(self._tasks):
            return False
        self._tasks[index - 1], self._tasks[index] = (
            self._tasks[index], self._tasks[index - 1]
        )
        self._reindex()
        return True

    def move_down(self, index: int) -> bool:
        """Move task at index one position down. Returns True if moved."""
        if index < 0 or index >= len(self._tasks) - 1:
            return False
        self._tasks[index], self._tasks[index + 1] = (
            self._tasks[index + 1], self._tasks[index]
        )
        self._reindex()
        return True

    # ── Polling ──────────────────────────────────────────────────────────────

    def tick_all(self) -> list[tuple[TaskProgressBar, object]]:
        """Tick every task and return list of (bar, snapshot) pairs."""
        return [(bar, bar.tick()) for bar in self._tasks]

    # ── Access ───────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._tasks)

    def __getitem__(self, index: int) -> TaskProgressBar:
        return self._tasks[index]

    def tasks(self) -> list[TaskProgressBar]:
        return list(self._tasks)

    def _reindex(self) -> None:
        for i, bar in enumerate(self._tasks):
            bar.position = i
