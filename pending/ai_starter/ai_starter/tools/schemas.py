"""Tool execution schemas."""

from enum import Enum

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Result of tool execution."""
    success: bool
    output: str
    error: str | None = None
    duration_ms: int


class ToolPermission(str, Enum):
    """Tool execution permission levels."""
    allowed = "allowed"
    ask_user = "ask_user"
    denied = "denied"
