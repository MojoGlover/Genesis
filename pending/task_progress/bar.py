"""
task_progress/bar.py
Core task tracking logic — no UI concerns here.
A TaskProgressBar tracks one task: polls a callable for completed units,
computes percentage, predicts ETA, and maintains pause/run state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ProgressSnapshot:
    completed: float
    projected: float
    pct: float               # 0.0 – 1.0
    elapsed: float           # seconds since start (or since last resume)
    rate: float              # units per second (rolling)
    eta_seconds: Optional[float]   # None if stalled or complete
    paused: bool
    done: bool


class TaskProgressBar:
    """
    Tracks a single task.

    Args:
        name:        Display name shown in the UI.
        projected:   Total expected workload (any unit — tokens, steps, bytes…).
        poll_fn:     Callable that returns current completed units (float).
                     Called on every interval tick.
        poll_interval_s: How often to poll (seconds). Default 1.0.
    """

    # How many recent samples to use for rate calculation
    _RATE_WINDOW = 8

    def __init__(
        self,
        name: str,
        projected: float,
        poll_fn: Callable[[], float],
        poll_interval_s: float = 1.0,
    ) -> None:
        self.name             = name
        self.projected        = max(projected, 1.0)   # guard div/0
        self.poll_fn          = poll_fn
        self.poll_interval_s  = poll_interval_s

        self._paused          = False
        self._completed       = 0.0
        self._start_time      = time.monotonic()
        self._last_poll_time  = self._start_time
        self._last_completed  = 0.0

        # Rolling window: list of (timestamp, completed) tuples
        self._history: list[tuple[float, float]] = []

        # Position in the queue (set by TaskQueue)
        self.position: int = 0

    # ── State ────────────────────────────────────────────────────────────────

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def toggle_pause(self) -> None:
        self._paused = not self._paused

    # ── Polling ──────────────────────────────────────────────────────────────

    def tick(self) -> ProgressSnapshot:
        """
        Poll the task for current progress.
        Safe to call at any frequency — respects poll_interval_s internally.
        Returns the latest ProgressSnapshot.
        """
        now = time.monotonic()

        if not self._paused:
            # Respect interval
            if (now - self._last_poll_time) >= self.poll_interval_s:
                try:
                    value = float(self.poll_fn())
                except Exception:
                    value = self._completed   # hold last value on error

                self._completed      = min(value, self.projected)
                self._last_poll_time = now

                # Record for rate calculation
                self._history.append((now, self._completed))
                if len(self._history) > self._RATE_WINDOW:
                    self._history.pop(0)

        return self._snapshot(now)

    def _snapshot(self, now: float) -> ProgressSnapshot:
        pct     = self._completed / self.projected
        elapsed = now - self._start_time
        done    = pct >= 1.0

        # Rolling rate (units/sec) from history window
        rate = 0.0
        if len(self._history) >= 2:
            t0, c0 = self._history[0]
            t1, c1 = self._history[-1]
            dt = t1 - t0
            if dt > 0:
                rate = (c1 - c0) / dt

        # ETA
        eta: Optional[float] = None
        if not done and not self._paused and rate > 0:
            remaining = self.projected - self._completed
            eta = remaining / rate

        return ProgressSnapshot(
            completed    = self._completed,
            projected    = self.projected,
            pct          = pct,
            elapsed      = elapsed,
            rate         = rate,
            eta_seconds  = eta,
            paused       = self._paused,
            done         = done,
        )

    # ── Convenience ──────────────────────────────────────────────────────────

    def reset(self, new_projected: Optional[float] = None) -> None:
        """Restart tracking from zero."""
        self._completed      = 0.0
        self._start_time     = time.monotonic()
        self._last_poll_time = self._start_time
        self._history.clear()
        if new_projected is not None:
            self.projected = max(new_projected, 1.0)
