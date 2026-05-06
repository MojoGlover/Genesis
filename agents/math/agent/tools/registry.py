"""
registry.py — Tool executor for the Math agent's ReAct loop.

Maps tool names to functions and generates tool docs injected into the system prompt.

Tool call format (LLM outputs this in its response):
    ```json
    {"tool": "solve", "params": {"operation": "add", "a": 3, "b": 4}}
    ```
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)


TOOL_DOCS = """
## TOOLS

When you need to compute an answer, output a JSON block (and ONLY this — no other text):

```json
{"tool": "solve", "params": {"operation": "<op>", "a": <0-9>, "b": <0-9>}}
```

After the tool runs you will see the result, then give your final response as plain text.

### solve — Arithmetic on single digits (0-9)

Operations: add | subtract | multiply | divide (floor division)

Examples:
```json
{"tool": "solve", "params": {"operation": "add", "a": 3, "b": 4}}
{"tool": "solve", "params": {"operation": "divide", "a": 9, "b": 2}}
```

### Rules
- Always use the solve tool to compute — never guess the answer.
- Only one tool call per turn.
- Both operands must be 0-9.
- Division by zero is an error — say so clearly.
"""


def build_executor() -> Callable[[str, dict], str]:
    """Build and return the math tool executor. Called once at boot."""
    import math as _math

    def execute(tool_name: str, params: dict) -> str:
        if tool_name != "solve":
            return f"Unknown tool: '{tool_name}'. Only 'solve' is available."

        operation = params.get("operation", "")
        a = params.get("a")
        b = params.get("b")

        if operation not in ("add", "subtract", "multiply", "divide"):
            return f"Unknown operation '{operation}'. Use: add, subtract, multiply, divide"

        try:
            a = int(a)
            b = int(b)
        except (TypeError, ValueError):
            return "Operands must be integers."

        if not (0 <= a <= 9 and 0 <= b <= 9):
            return f"Operands must be 0-9. Got a={a}, b={b}"

        if operation == "divide" and b == 0:
            return "Error: division by zero"

        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            result = _math.floor(a / b)

        return json.dumps({"result": result, "operation": operation, "input": {"a": a, "b": b}})

    return execute


def parse_tool_call(text: str) -> dict | None:
    """
    Extract a tool call JSON from LLM output.
    Returns None if no valid tool call found.
    """
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if block_match:
        try:
            data = json.loads(block_match.group(1))
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass

    bare_match = re.search(r'\{[^{}]*"tool"\s*:[^{}]*\}', text, re.DOTALL)
    if bare_match:
        try:
            data = json.loads(bare_match.group(0))
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass

    return None
