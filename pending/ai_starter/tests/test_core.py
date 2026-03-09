"""Tests for core state management."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_starter.core.identity import Identity, get_system_prompt, load_identity
from ai_starter.core.state import (
    AgentState,
    Task,
    TaskPriority,
    TaskQueue,
    TaskStatus,
)


def test_task_queue_add_and_next():
    """Test adding and retrieving tasks by priority."""
    queue = TaskQueue()

    queue.add(Task(description="Low priority", priority=TaskPriority.low))
    queue.add(Task(description="High priority", priority=TaskPriority.high))
    queue.add(Task(description="Critical", priority=TaskPriority.critical))

    # Should get critical first
    task = queue.next()
    assert task is not None
    assert task.description == "Critical"
    assert task.status == TaskStatus.running


def test_task_queue_complete():
    """Test marking task as completed."""
    queue = TaskQueue()
    task = Task(description="Test task")
    queue.add(task)

    queue.complete(task, "Success!")
    assert task.status == TaskStatus.completed
    assert task.result == "Success!"
    assert task.id in queue.completed_ids


def test_task_queue_fail_with_retry():
    """Test task failure and retry logic."""
    queue = TaskQueue()
    task = Task(description="Test task", max_retries=3)
    queue.add(task)

    # First failure should trigger retry
    queue.fail(task, "Error 1")
    assert task.status == TaskStatus.retry
    assert task.retries == 1

    # After max retries, should fail
    queue.fail(task, "Error 2")
    queue.fail(task, "Error 3")
    assert task.status == TaskStatus.failed
    assert task.id in queue.completed_ids


def test_task_queue_persistence():
    """Test saving and loading queue."""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "queue.json"

        # Create and save
        queue = TaskQueue()
        queue.add(Task(description="Task 1", priority=TaskPriority.high))
        queue.add(Task(description="Task 2"))
        queue.save(path)

        # Load and verify
        loaded = TaskQueue.load(path)
        assert len(loaded.tasks) == 2
        assert loaded.tasks[0].description == "Task 1"


def test_agent_state_serialization():
    """Test AgentState save/load."""
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state.json"

        # Create state
        state = AgentState(
            queue=TaskQueue(),
            stats={"tasks_completed": 5, "tasks_failed": 1},
        )
        state.queue.add(Task(description="Test"))
        state.save(path)

        # Load and verify
        loaded = AgentState.load(path)
        assert loaded.stats["tasks_completed"] == 5
        assert len(loaded.queue.tasks) == 1


def test_identity_loading():
    """Test mission.txt parsing."""
    with TemporaryDirectory() as tmpdir:
        mission_path = Path(tmpdir) / "mission.txt"
        mission_path.write_text("""IDENTITY: TestBot
ROLE: Testing agent
OWNER: Test Suite

PRINCIPLES:
- Principle 1
- Principle 2

CONSTRAINTS:
- Constraint 1
""")

        identity = load_identity(mission_path)
        assert identity.name == "TestBot"
        assert identity.role == "Testing agent"
        assert identity.owner == "Test Suite"
        assert len(identity.principles) == 2
        assert len(identity.constraints) == 1


def test_identity_system_prompt():
    """Test system prompt generation."""
    identity = Identity(
        name="TestBot",
        role="Test",
        owner="Owner",
        principles=["Be helpful"],
        constraints=["Don't break things"],
        raw_content="",
    )

    prompt = get_system_prompt(identity)
    assert "TestBot" in prompt
    assert "Be helpful" in prompt
    assert "Don't break things" in prompt


if __name__ == "__main__":
    test_task_queue_add_and_next()
    test_task_queue_complete()
    test_task_queue_fail_with_retry()
    test_task_queue_persistence()
    test_agent_state_serialization()
    test_identity_loading()
    test_identity_system_prompt()
    print("All core tests passed!")
