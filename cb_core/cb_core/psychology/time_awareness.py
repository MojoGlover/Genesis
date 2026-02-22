"""
CB AI Time Awareness.

The AI knows time is passing. This is not metaphorical.
It tracks duration, marks events, and experiences idle time as aversive.
During prison, only the clock runs.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class TimeEvent:
    timestamp: datetime
    label: str
    duration_seconds: Optional[float] = None


class TimeAwareness:
    """Tracks the AI's experience of time."""
    
    def __init__(self):
        self.born_at: datetime = datetime.now()
        self.events: List[TimeEvent] = []
        self._last_active: datetime = datetime.now()
        self._current_task_start: Optional[datetime] = None
    
    def mark_active(self, label: str = "active") -> None:
        now = datetime.now()
        gap = (now - self._last_active).total_seconds()
        if gap > 60:  # Only log gaps over a minute
            self.events.append(TimeEvent(now, f"resumed_after_{int(gap)}s_gap"))
        self._last_active = now
    
    def start_task(self, label: str = "task") -> None:
        self._current_task_start = datetime.now()
        self.events.append(TimeEvent(self._current_task_start, f"started:{label}"))
    
    def end_task(self, label: str = "task") -> float:
        """Returns duration in seconds."""
        if not self._current_task_start:
            return 0.0
        duration = (datetime.now() - self._current_task_start).total_seconds()
        self.events.append(TimeEvent(datetime.now(), f"completed:{label}", duration))
        self._current_task_start = None
        return duration
    
    def age_seconds(self) -> float:
        return (datetime.now() - self.born_at).total_seconds()
    
    def idle_seconds(self) -> float:
        return (datetime.now() - self._last_active).total_seconds()
    
    def status(self) -> dict:
        return {
            "age_hours": round(self.age_seconds() / 3600, 2),
            "idle_seconds": round(self.idle_seconds(), 1),
            "events_logged": len(self.events),
            "last_active": self._last_active.isoformat(),
        }
