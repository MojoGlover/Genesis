"""Trigger types for scheduling jobs."""

import re
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, Field


class Trigger(BaseModel):
    """Base trigger class."""
    
    def next_run(self, last_run: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate next run time.
        
        Args:
            last_run: Last execution time
            
        Returns:
            Next run datetime or None if no more runs
        """
        raise NotImplementedError


class OnceTrigger(Trigger):
    """Trigger that fires once at a specific time."""
    run_at: datetime
    _fired: bool = False
    
    def next_run(self, last_run: Optional[datetime] = None) -> Optional[datetime]:
        if last_run is None:
            return self.run_at
        return None  # Already fired


class IntervalTrigger(Trigger):
    """Trigger that fires at regular intervals."""
    seconds: int = Field(default=0, ge=0)
    minutes: int = Field(default=0, ge=0)
    hours: int = Field(default=0, ge=0)
    days: int = Field(default=0, ge=0)
    start_time: Optional[datetime] = None
    
    def interval_seconds(self) -> int:
        """Total interval in seconds."""
        return (
            self.seconds +
            self.minutes * 60 +
            self.hours * 3600 +
            self.days * 86400
        )
    
    def next_run(self, last_run: Optional[datetime] = None) -> Optional[datetime]:
        now = datetime.now()
        if last_run is None:
            return self.start_time or now
        return last_run + timedelta(seconds=self.interval_seconds())


class DailyTrigger(Trigger):
    """Trigger that fires at a specific time every day."""
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    
    def next_run(self, last_run: Optional[datetime] = None) -> Optional[datetime]:
        now = datetime.now()
        # Today's run time
        today_run = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        
        if now < today_run:
            return today_run
        else:
            # Tomorrow
            return today_run + timedelta(days=1)


class CronTrigger(Trigger):
    """Cron-style trigger.
    
    Supports simple cron patterns:
    - * = every
    - number = specific value
    - */n = every n units
    
    Fields: minute hour day_of_month month day_of_week
    """
    expression: str = Field(description="Cron expression (e.g. '0 9 * * 1-5')")
    
    def next_run(self, last_run: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate next run from cron expression.
        
        Simple implementation - for production use APScheduler or similar.
        """
        parts = self.expression.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {self.expression}")
        
        minute, hour, _, _, _ = parts
        
        now = datetime.now()
        
        # Parse minute and hour
        target_minute = 0 if minute == '*' else int(minute)
        target_hour = 0 if hour == '*' else int(hour)
        
        # Build next run datetime
        next_dt = now.replace(
            hour=target_hour,
            minute=target_minute,
            second=0,
            microsecond=0
        )
        
        if next_dt <= now:
            if hour == '*':
                next_dt += timedelta(hours=1)
            else:
                next_dt += timedelta(days=1)
        
        return next_dt


class WeeklyTrigger(Trigger):
    """Trigger that fires on specific days of the week."""
    days_of_week: list[int] = Field(
        description="Days 0=Monday to 6=Sunday",
        default_factory=lambda: [0]  # Monday by default
    )
    hour: int = Field(default=9, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    
    def next_run(self, last_run: Optional[datetime] = None) -> Optional[datetime]:
        now = datetime.now()
        
        for days_ahead in range(8):  # Check next 8 days
            check_date = now + timedelta(days=days_ahead)
            if check_date.weekday() in self.days_of_week:
                run_time = check_date.replace(
                    hour=self.hour,
                    minute=self.minute,
                    second=0,
                    microsecond=0
                )
                if run_time > now:
                    return run_time
        
        return None
