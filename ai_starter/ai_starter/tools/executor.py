"""Tool execution with safety checks."""

import time
from typing import Any

from ai_starter.llm.schemas import ToolCall
from ai_starter.tools.registry import ToolRegistry
from ai_starter.tools.schemas import ToolResult


class ToolExecutor:
    """Executes tools with validation and safety."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute a tool call and return result."""
        start_time = time.perf_counter()

        # Lookup tool
        tool = self.registry.get(call.tool_name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool not found: {call.tool_name}",
                duration_ms=0,
            )

        # Execute with timeout
        try:
            output = tool.fn(**call.arguments)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Truncate output if too large
            if isinstance(output, str) and len(output) > 65536:
                output = output[:65536] + "\n... (truncated)"

            return ToolResult(
                success=True,
                output=str(output),
                error=None,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                duration_ms=duration_ms,
            )

    def is_allowed(self, call: ToolCall) -> bool:
        """Check if tool execution is permitted."""
        # For now, all registered tools are allowed
        # Future: add permission rules, user confirmation, etc.
        return self.registry.get(call.tool_name) is not None
