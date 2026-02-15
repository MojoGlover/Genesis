"""Tests for memory storage and retrieval."""

from pathlib import Path
from tempfile import TemporaryDirectory

from ai_starter.core.state import Task, TaskPriority
from ai_starter.memory.retrieval import retrieve_context, retrieve_learnings
from ai_starter.memory.schemas import MemoryCategory, MemoryItem
from ai_starter.memory.storage import MemoryStore


def test_memory_store_and_retrieve():
    """Test storing and retrieving memories."""
    with TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "test.db")

        # Store items
        store.store(
            MemoryItem(
                category=MemoryCategory.task_result,
                content="Completed task A",
            )
        )
        store.store(
            MemoryItem(
                category=MemoryCategory.learning,
                content="Learned X",
            )
        )

        # Retrieve recent
        recent = store.get_recent(limit=10)
        assert len(recent) == 2

        # Filter by category
        learnings = store.get_recent(limit=10, category=MemoryCategory.learning)
        assert len(learnings) == 1
        assert learnings[0].content == "Learned X"

        store.close()


def test_memory_fts_search():
    """Test full-text search."""
    with TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "test.db")

        store.store(
            MemoryItem(
                category=MemoryCategory.task_result,
                content="Task about database optimization",
            )
        )
        store.store(
            MemoryItem(
                category=MemoryCategory.task_result,
                content="Task about UI design",
            )
        )

        # Search for "database"
        results = store.search("database", limit=10)
        assert len(results) == 1
        assert "database" in results[0].content

        store.close()


def test_memory_count_and_cleanup():
    """Test counting and cleanup."""
    with TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "test.db")

        for i in range(5):
            store.store(
                MemoryItem(
                    category=MemoryCategory.observation,
                    content=f"Observation {i}",
                )
            )

        assert store.count() == 5

        # Cleanup old items (nothing should be deleted since they're new)
        deleted = store.cleanup(older_than_days=1)
        assert deleted == 0
        assert store.count() == 5

        store.close()


def test_retrieve_context():
    """Test context retrieval for tasks."""
    with TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "test.db")

        store.store(
            MemoryItem(
                category=MemoryCategory.task_result,
                content="Relevant information about databases",
            )
        )

        task = Task(description="Optimize database queries", priority=TaskPriority.high)
        context = retrieve_context(store, task, limit=5)

        assert "database" in context.lower()

        store.close()


def test_retrieve_learnings():
    """Test learning retrieval."""
    with TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "test.db")

        store.store(
            MemoryItem(
                category=MemoryCategory.learning,
                content="Always validate input",
            )
        )
        store.store(
            MemoryItem(
                category=MemoryCategory.learning,
                content="Use async for I/O",
            )
        )

        learnings = retrieve_learnings(store, limit=10)
        assert len(learnings) == 2
        # Check that one of them contains the expected text
        assert any("validate input" in l for l in learnings)

        store.close()


if __name__ == "__main__":
    test_memory_store_and_retrieve()
    test_memory_fts_search()
    test_memory_count_and_cleanup()
    test_retrieve_context()
    test_retrieve_learnings()
    print("All memory tests passed!")
