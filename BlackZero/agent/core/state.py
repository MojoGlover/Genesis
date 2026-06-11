"""
state.py — Pydantic models for all BlackZero agent state.
Every piece of data that moves through the agent is typed here.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class AgentIdentity(BaseModel):
    name: str
    alias: str
    role: str
    owner: str = "Computer Black"
    model: str
    capabilities: list[str] = Field(default_factory=list)


class AgentState(BaseModel):
    message: str = ""
    from_agent: str = ""
    session_id: str = ""
    memory_context: list[str] = Field(default_factory=list)
    mission_context: str = ""        # loaded at boot, injected into every LLM call
    response: str = ""
    bootstrap_verified: bool = False
    error: Optional[str] = None
    # ReAct loop fields
    tool_history: list[dict] = Field(default_factory=list)  # [{role, content}] accumulated turns
    tool_iterations: int = 0
    max_iterations: int = 6    # must match MAX_TOOL_ITERATIONS in graph.py
    tool_required: bool = False  # True when _requires_tool_use matched the message
    tool_call_pending: bool = False
    force_rethink: bool = False
    tools_ran: int = 0
    last_result: dict = Field(default_factory=dict)
    data_dir: str = ""
