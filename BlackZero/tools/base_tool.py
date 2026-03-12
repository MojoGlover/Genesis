# base_tool.py
# THE BASE TOOL INTERFACE
#
# Responsibility:
#   Defines the contract that every tool must implement.
#   All tools registered in the ToolRegistry must subclass BaseTool.
#
# What does NOT belong here:
#   - Specific tool implementations (each gets its own file)
#   - Registry logic (that belongs in tool_registry.py)

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ToolError(Exception):
    """Raised when a tool fails to execute. Include a human-readable message."""


class BaseTool(ABC):
    """
    Abstract base class for all agent tools.

    A tool is a named, callable capability that the executor can invoke by
    name. Tools must be stateless where possible — they receive an input dict,
    do work, and return a result dict.

    Example implementation:
        class WebSearchTool(BaseTool):
            name = "web_search"
            description = "Searches the web and returns relevant results."

            def run(self, input: dict) -> dict:
                query = input["query"]
                results = do_search(query)
                return {"ok": True, "results": results}
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique snake_case identifier for this tool.
        Used by executor and planner to select and call the tool by name.
        """

    @property
    @abstractmethod
    def description(self) -> str:
        """
        One-sentence description of what this tool does.
        Used by the planner to decide when to invoke this tool.
        """

    @abstractmethod
    def run(self, input: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the tool with the given input and return the result.

        Args:
            input: Tool-specific key-value input. Document the expected schema
                   in the tool's class docstring.

        Returns:
            A dict containing the tool output. Must always include:
                {"ok": True, ...result payload...}
            On failure, raise ToolError — do not return ok=False silently.

        Raises:
            ToolError: If execution fails in a predictable way.
        """

    def validate_input(self, input: dict[str, Any], required_keys: list[str]) -> None:
        """
        Raise ToolError if any required key is missing from input.
        Call at the top of run() for fast failure on bad input.
        """
        missing = [k for k in required_keys if k not in input]
        if missing:
            raise ToolError(f"{self.name}: missing required input keys: {missing}")
