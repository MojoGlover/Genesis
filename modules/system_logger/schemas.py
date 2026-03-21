"""
system_logger schemas — structured log entries and query filters.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class LogLevel(str, Enum):
    DEBUG   = "debug"
    INFO    = "info"
    WARNING = "warning"
    ERROR   = "error"
    CRITICAL = "critical"


class LogEntry(BaseModel):
    """A single structured log entry from any agent or module."""
    agent_id:   str                          = Field(..., description="ID of the agent or module submitting the log")
    agent_name: str                          = Field(..., description="Human-readable agent name")
    level:      LogLevel                     = Field(..., description="Log severity level")
    message:    str                          = Field(..., description="Log message")
    context:    Optional[Dict[str, Any]]     = Field(default=None, description="Optional structured context (stack trace, inputs, etc.)")
    timestamp:  Optional[datetime]           = Field(default=None, description="Timestamp — server fills this if omitted")


class LogQuery(BaseModel):
    """Filter parameters for log queries."""
    agent_id:   Optional[str]       = None
    level:      Optional[LogLevel]  = None
    since:      Optional[datetime]  = None
    limit:      int                 = Field(default=100, le=1000)


class LogSummary(BaseModel):
    """Per-agent summary for the dashboard."""
    agent_id:       str
    agent_name:     str
    total:          int
    errors:         int
    warnings:       int
    last_seen:      Optional[datetime]
    last_error:     Optional[str]
    last_error_at:  Optional[datetime]


class IngestResponse(BaseModel):
    ok:         bool
    log_id:     str
    timestamp:  datetime
