"""Prompt construction for different agent phases."""

from ai_starter.core.identity import Identity
from ai_starter.core.state import Step, StepResult, Task
from ai_starter.tools.registry import ToolSpec


def build_system_prompt(identity: Identity) -> str:
    """Build system prompt from identity."""
    return f"""You are {identity.name}.

ROLE: {identity.role}

You operate under the authority of: {identity.owner}

PRINCIPLES:
{chr(10).join(f'- {p}' for p in identity.principles)}

CONSTRAINTS (you MUST follow these):
{chr(10).join(f'- {c}' for c in identity.constraints)}

Always respond in structured formats when requested. Be precise and actionable."""


def build_plan_prompt(task: Task, tools: list[ToolSpec]) -> str:
    """Ask LLM to break task into executable steps."""
    tools_desc = "\n".join(
        f"- {tool.name}: {tool.description}" for tool in tools
    )

    return f"""Task: {task.description}

Available tools:
{tools_desc}

Break this task into a series of steps. Each step should use one tool.

Respond in this JSON format:
{{
  "steps": [
    {{"description": "step description", "tool_name": "tool_name", "tool_args": {{"arg": "value"}}}},
    ...
  ]
}}"""


def build_execute_prompt(step: Step, context: str) -> str:
    """Format step for execution (if LLM involvement needed)."""
    return f"""Execute this step:
{step.description}

Context:
{context}

Use tool: {step.tool_name}
Arguments: {step.tool_args}"""


def build_reflect_prompt(task: Task, results: list[StepResult]) -> str:
    """Ask LLM to reflect on task execution."""
    results_summary = "\n".join(
        f"- {'✓' if r.success else '✗'} {r.output[:200]}" for r in results
    )

    return f"""Task: {task.description}

Execution results:
{results_summary}

Reflect on this execution. Did it succeed? What did we learn?

Respond in this JSON format:
{{
  "success": true/false,
  "summary": "brief summary",
  "learnings": ["learning 1", "learning 2"],
  "next_actions": ["action 1", "action 2"]
}}"""


def build_tool_call_prompt(step: Step, tools: list[ToolSpec]) -> str:
    """Format tool specs for LLM consumption."""
    tool_desc = next((t.description for t in tools if t.name == step.tool_name), "")
    return f"""Use tool: {step.tool_name}
Description: {tool_desc}
Args: {step.tool_args}"""
