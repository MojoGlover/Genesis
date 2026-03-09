"""Pydantic models for scheduler."""

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class JobResult(BaseModel):
    """Result of a job execution."""
    job_id: str
    status: JobStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Any = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


class JobHistory(BaseModel):
    """History entry for a job run."""
    run_id: str
    job_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: JobStatus
    error: Optional[str] = None
    duration_seconds: float = 0.0


class SchedulerState(BaseModel):
    """Current state of the scheduler."""
    running: bool = False
    total_jobs: int = 0
    pending_jobs: int = 0
    running_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    paused_jobs: int = 0
