"""Tool registration with decorator-based API."""

import inspect
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Tool specification for LLM consumption."""
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)  # JSON Schema format
    category: str = "general"
    fn: Any = None  # The actual callable


class ToolRegistry:
    """Central registry for agent tools."""

    def __init__(self):
        self.tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        fn: Callable,
        category: str = "general",
    ) -> ToolSpec:
        """Register a tool function."""
        # Extract parameters from function signature
        sig = inspect.signature(fn)
        parameters = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        for param_name, param in sig.parameters.items():
            param_type = "string"  # Default
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == bool:
                    param_type = "boolean"

            parameters["properties"][param_name] = {"type": param_type}
            if param.default == inspect.Parameter.empty:
                parameters["required"].append(param_name)

        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            category=category,
            fn=fn,
        )
        self.tools[name] = spec
        return spec

    def get(self, name: str) -> ToolSpec | None:
        """Get tool by name."""
        return self.tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        """List all registered tools."""
        return list(self.tools.values())

    def get_for_llm(self) -> str:
        """Format tools for LLM prompt."""
        lines = ["Available tools:"]
        for tool in self.list_tools():
            lines.append(f"\n{tool.name}: {tool.description}")
            if tool.parameters.get("properties"):
                lines.append("  Parameters:")
                for param, schema in tool.parameters["properties"].items():
                    required = " (required)" if param in tool.parameters.get("required", []) else ""
                    lines.append(f"    - {param}: {schema['type']}{required}")
        return "\n".join(lines)


def tool(name: str, description: str, category: str = "general"):
    """Decorator for registering tool functions."""
    def decorator(fn: Callable) -> Callable:
        fn._tool_name = name
        fn._tool_description = description
        fn._tool_category = category
        return fn
    return decorator


# Built-in tools

def shell_execute(command: str) -> str:
    """Execute a shell command safely and return output."""
    try:
        # Use shlex to prevent injection
        safe_cmd = shlex.split(command)
        result = subprocess.run(
            safe_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        return output[:4096]  # Truncate
    except Exception as e:
        return f"Error: {e}"


def file_read(path: str) -> str:
    """Read file contents."""
    try:
        content = Path(path).expanduser().read_text()
        return content[:8192]  # Truncate large files
    except Exception as e:
        return f"Error reading file: {e}"


def file_write(path: str, content: str) -> str:
    """Write content to file."""
    try:
        file_path = Path(path).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


# Register built-ins
def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register the 3 built-in tools."""
    registry.register("shell_execute", "Execute a shell command", shell_execute, "system")
    registry.register("file_read", "Read a file", file_read, "filesystem")
    registry.register("file_write", "Write to a file", file_write, "filesystem")
