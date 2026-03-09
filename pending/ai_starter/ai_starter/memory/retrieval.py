"""Context retrieval from memory."""

from ai_starter.core.state import Task
from ai_starter.memory.schemas import MemoryCategory
from ai_starter.memory.storage import MemoryStore


def retrieve_context(store: MemoryStore, task: Task, limit: int = 5) -> str:
    """Search memories relevant to task and format as context string."""
    # Try FTS search first
    results = store.search(task.description, limit=limit)

    if not results:
        # Fall back to recent memories
        results = store.get_recent(limit=limit)

    if not results:
        return "No prior context available."

    context_lines = ["Relevant context from memory:"]
    for item in results:
        context_lines.append(f"- [{item.category.value}] {item.content}")

    return "\n".join(context_lines)


def retrieve_learnings(store: MemoryStore, limit: int = 10) -> list[str]:
    """Get recent learnings for self-improvement."""
    learnings = store.get_recent(limit=limit, category=MemoryCategory.learning)
    return [item.content for item in learnings]
