"""Math tool — add, subtract, multiply, floor-divide single digits."""
from __future__ import annotations

import math
from langchain_core.tools import tool


@tool
def solve(operation: str, a: int, b: int) -> dict:
    """
    Solve a basic arithmetic problem.

    Args:
        operation: one of 'add', 'subtract', 'multiply', 'divide'
        a: first operand (0-9)
        b: second operand (0-9)

    Returns:
        dict with result, operation, and input values
    """
    if operation not in ("add", "subtract", "multiply", "divide"):
        raise ValueError(f"Unknown operation '{operation}'. Use: add, subtract, multiply, divide")

    if not (0 <= a <= 9 and 0 <= b <= 9):
        raise ValueError(f"Operands must be 0-9. Got a={a}, b={b}")

    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Division by zero")
        result = math.floor(a / b)

    return {"result": result, "operation": operation, "input": {"a": a, "b": b}}
