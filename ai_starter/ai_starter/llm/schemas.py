"""LLM I/O models for Ollama interactions."""

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A chat message with role and content."""
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMResponse(BaseModel):
    """Response from Ollama generate call."""
    content: str
    model: str
    latency_ms: int
    raw: dict = Field(default_factory=dict)


class ToolCall(BaseModel):
    """Parsed tool invocation from LLM output."""
    tool_name: str
    arguments: dict = Field(default_factory=dict)
