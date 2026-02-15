"""Tests for LLM prompt building and response parsing."""

from ai_starter.core.identity import Identity
from ai_starter.core.state import Step, StepResult, Task, TaskPriority
from ai_starter.llm.prompt_builder import (
    build_plan_prompt,
    build_reflect_prompt,
    build_system_prompt,
)
from ai_starter.llm.response_parser import extract_json, parse_plan, parse_reflection
from ai_starter.tools.registry import ToolSpec


def test_build_system_prompt():
    """Test system prompt construction."""
    identity = Identity(
        name="TestBot",
        role="Test Agent",
        owner="Test",
        principles=["Be helpful"],
        constraints=["Be safe"],
        raw_content="",
    )

    prompt = build_system_prompt(identity)
    assert "TestBot" in prompt
    assert "Test Agent" in prompt
    assert "Be helpful" in prompt
    assert "Be safe" in prompt


def test_build_plan_prompt():
    """Test planning prompt construction."""
    task = Task(description="Write hello world", priority=TaskPriority.medium)
    tools = [
        ToolSpec(
            name="file_write",
            description="Write to file",
            parameters={},
        )
    ]

    prompt = build_plan_prompt(task, tools)
    assert "Write hello world" in prompt
    assert "file_write" in prompt
    assert "JSON" in prompt


def test_build_reflect_prompt():
    """Test reflection prompt construction."""
    task = Task(description="Test task")
    results = [
        StepResult(success=True, output="Done", duration_ms=100),
        StepResult(success=False, output="", error="Failed", duration_ms=50),
    ]

    prompt = build_reflect_prompt(task, results)
    assert "Test task" in prompt
    assert "✓" in prompt  # Success indicator
    assert "✗" in prompt  # Failure indicator


def test_extract_json():
    """Test JSON extraction from text."""
    # JSON in code block
    text1 = '```json\n{"key": "value"}\n```'
    assert extract_json(text1) == {"key": "value"}

    # Raw JSON
    text2 = 'Some text {"key": "value"} more text'
    assert extract_json(text2) == {"key": "value"}

    # No JSON
    text3 = "No JSON here"
    assert extract_json(text3) is None


def test_parse_plan():
    """Test plan parsing from LLM response."""
    response = """```json
{
  "steps": [
    {"description": "Step 1", "tool_name": "tool1", "tool_args": {"arg": "val"}},
    {"description": "Step 2", "tool_name": "tool2", "tool_args": {}}
  ]
}
```"""

    steps = parse_plan(response)
    assert len(steps) == 2
    assert steps[0].description == "Step 1"
    assert steps[0].tool_name == "tool1"
    assert steps[1].tool_args == {}


def test_parse_reflection():
    """Test reflection parsing."""
    response = """```json
{
  "success": true,
  "summary": "Task completed",
  "learnings": ["Learning 1", "Learning 2"],
  "next_actions": ["Action 1"]
}
```"""

    reflection = parse_reflection(response)
    assert reflection.success is True
    assert reflection.summary == "Task completed"
    assert len(reflection.learnings) == 2
    assert len(reflection.next_actions) == 1


if __name__ == "__main__":
    test_build_system_prompt()
    test_build_plan_prompt()
    test_build_reflect_prompt()
    test_extract_json()
    test_parse_plan()
    test_parse_reflection()
    print("All LLM tests passed!")
