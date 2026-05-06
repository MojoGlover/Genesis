"""
registry.py — Tool registry stub for ToolZero-stamped agents.

Fill this in when stamping a specific tool-agent.
Each tool is a plain function: (params: dict) -> str

Tool-agents do NOT inject docs into an LLM prompt.
They just execute and return.
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# ── Tool map ──────────────────────────────────────────────────────────────────
# key: tool name (string the caller uses)
# value: function that takes params dict, returns result string

TOOLS: dict[str, Callable[[dict], str]] = {
    # "example_tool": _example_tool,
}

# ── Executor ──────────────────────────────────────────────────────────────────

def execute(tool_name: str, params: dict) -> str:
    """
    Dispatch a tool call. Returns result as string.
    Raises KeyError for unknown tools — caller handles it.
    """
    if tool_name not in TOOLS:
        available = list(TOOLS.keys())
        raise KeyError(f"Unknown tool '{tool_name}'. Available: {available}")

    fn = TOOLS[tool_name]
    try:
        return fn(params)
    except TypeError as e:
        raise TypeError(f"Tool '{tool_name}' bad params: {e}") from e


def list_tools() -> list[str]:
    return list(TOOLS.keys())
