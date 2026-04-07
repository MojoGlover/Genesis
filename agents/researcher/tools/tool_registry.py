# tool_registry.py
# THE TOOL REGISTRY
#
# Responsibility:
#   Maintains the list of all tools available to this agent and provides
#   a lookup interface for executor.py to find and call tools by name.
#
# What does NOT belong here:
#   - Individual tool implementations (each tool gets its own file)
#   - Execution orchestration (that belongs in executor.py)
#   - One-off scripts or experiments (those go to pending/)

from __future__ import annotations

from typing import Any

from BlackZero.tools.base_tool import BaseTool, ToolError


class ToolRegistry:
    """
    Central registry for all tools available to an agent.

    The executor calls run_tool() by name. Tools are registered at
    agent startup and must not be modified at runtime.

    Usage:
        registry = ToolRegistry()
        registry.register(WebSearchTool())
        registry.register(CodeRunnerTool())

        result = registry.run_tool("web_search", {"query": "latest news"})
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """
        Add a tool to the registry.
        Raises ValueError if a tool with the same name is already registered.
        """
        if tool.name in self._tools:
            raise ValueError(
                f"ToolRegistry: tool '{tool.name}' is already registered. "
                "Each tool must have a unique name."
            )
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Return the tool with the given name, or None if not registered."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, str]]:
        """
        Return a summary of all registered tools.

        Returns:
            List of {"name": str, "description": str} dicts,
            sorted alphabetically by name.
        """
        return [
            {"name": t.name, "description": t.description}
            for t in sorted(self._tools.values(), key=lambda t: t.name)
        ]

    def run_tool(self, name: str, input: dict[str, Any]) -> dict[str, Any]:
        """
        Look up and execute a tool by name.

        Args:
            name:  The tool's registered name.
            input: Input dict passed directly to the tool's run() method.

        Returns:
            The tool's result dict.

        Raises:
            ToolError: If the tool name is not registered, or the tool itself raises.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(
                f"ToolRegistry: no tool named '{name}' is registered. "
                f"Available tools: {list(self._tools.keys())}"
            )
        return tool.run(input)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
