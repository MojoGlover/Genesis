"""Parse LLM text responses into structured data."""

import json
import re

from ai_starter.core.state import Reflection, Step
from ai_starter.llm.schemas import ToolCall


def extract_json(raw: str) -> dict | None:
    """Find and parse JSON block in free text."""
    # Try to find JSON in code blocks
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def parse_plan(raw: str) -> list[Step]:
    """Extract step list from LLM response."""
    data = extract_json(raw)
    if not data or "steps" not in data:
        return []

    steps = []
    for step_data in data["steps"]:
        try:
            steps.append(
                Step(
                    description=step_data.get("description", ""),
                    tool_name=step_data.get("tool_name", ""),
                    tool_args=step_data.get("tool_args", {}),
                )
            )
        except Exception:
            continue

    return steps


def parse_tool_call(raw: str) -> ToolCall | None:
    """Extract tool invocation from LLM response."""
    data = extract_json(raw)
    if not data:
        return None

    if "tool_name" in data and "arguments" in data:
        return ToolCall(
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
        )

    return None


def parse_reflection(raw: str) -> Reflection:
    """Extract reflection from LLM response."""
    data = extract_json(raw)
    if not data:
        return Reflection(
            success=False,
            summary="Failed to parse reflection",
            learnings=[],
            next_actions=[],
        )

    return Reflection(
        success=data.get("success", False),
        summary=data.get("summary", ""),
        learnings=data.get("learnings", []),
        next_actions=data.get("next_actions", []),
    )
