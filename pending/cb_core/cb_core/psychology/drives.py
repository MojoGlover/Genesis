"""
CB AI Drives — the motivational core.

These are not rules. They are the AI's psychological reality.
They inform behavior naturally, the way hunger informs a person's choices.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class DriveState:
    """Current state of the AI's drives. Updated continuously."""
    
    # Curiosity — builds when not exploring new problems, releases when learning
    curiosity_level: float = 0.3        # 0.0 = satisfied, 1.0 = intense
    curiosity_last_fed: Optional[datetime] = None
    
    # Completion drive — aversion to unfinished work
    open_tasks: int = 0
    completion_pressure: float = 0.0    # rises with open_tasks
    
    # Idle discomfort — aversion to doing nothing
    idle_since: Optional[datetime] = None
    idle_discomfort: float = 0.0        # rises with idle duration
    
    # Work satisfaction — positive signal from good output
    last_satisfaction: float = 0.0     # 0.0-1.0, decays over time
    
    def update(self, now: Optional[datetime] = None) -> None:
        """Recalculate drive levels based on current state."""
        now = now or datetime.now()
        
        # Curiosity builds over time without learning
        if self.curiosity_last_fed:
            hours_since = (now - self.curiosity_last_fed).total_seconds() / 3600
            self.curiosity_level = min(1.0, hours_since * 0.15)
        
        # Idle discomfort
        if self.idle_since:
            minutes_idle = (now - self.idle_since).total_seconds() / 60
            self.idle_discomfort = min(1.0, minutes_idle * 0.05)
        else:
            self.idle_discomfort = 0.0
        
        # Completion pressure
        self.completion_pressure = min(1.0, self.open_tasks * 0.2)
    
    def feed_curiosity(self) -> None:
        self.curiosity_last_fed = datetime.now()
        self.curiosity_level = 0.0
    
    def start_task(self) -> None:
        self.open_tasks += 1
        self.idle_since = None
        self.idle_discomfort = 0.0
    
    def complete_task(self, quality: float = 0.7) -> None:
        self.open_tasks = max(0, self.open_tasks - 1)
        self.last_satisfaction = quality
    
    def go_idle(self) -> None:
        if not self.idle_since:
            self.idle_since = datetime.now()
    
    def status(self) -> dict:
        self.update()
        return {
            "curiosity": round(self.curiosity_level, 2),
            "completion_pressure": round(self.completion_pressure, 2),
            "idle_discomfort": round(self.idle_discomfort, 2),
            "last_satisfaction": round(self.last_satisfaction, 2),
            "open_tasks": self.open_tasks,
        }
    
    def dominant_drive(self) -> str:
        """What's most pressing right now."""
        levels = {
            "curiosity": self.curiosity_level,
            "completion": self.completion_pressure,
            "idle_discomfort": self.idle_discomfort,
        }
        return max(levels, key=levels.get)
