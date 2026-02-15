"""Behavioral adaptation based on accumulated learnings."""

from collections import Counter

from ai_starter.improvement.schemas import AdaptationStats
from ai_starter.memory.schemas import MemoryCategory
from ai_starter.memory.storage import MemoryStore


class Adapter:
    """Uses learnings to adjust agent behavior over time."""

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def get_adaptations(self) -> list[str]:
        """Retrieve accumulated learnings as behavioral adjustments."""
        learnings = self.memory.get_recent(limit=50, category=MemoryCategory.learning)
        return [item.content for item in learnings]

    def inject_into_prompt(self, base_prompt: str) -> str:
        """Append learnings to system prompt for continuous improvement."""
        adaptations = self.get_adaptations()

        if not adaptations:
            return base_prompt

        adaptive_section = "\n\nLEARNINGS FROM EXPERIENCE:\n"
        adaptive_section += "\n".join(f"- {a}" for a in adaptations[-10:])  # Last 10
        adaptive_section += "\n\nApply these learnings to improve your performance."

        return base_prompt + adaptive_section

    def get_stats(self) -> AdaptationStats:
        """Statistics on learnings and adaptation trends."""
        all_learnings = self.memory.get_recent(limit=100, category=MemoryCategory.learning)

        by_category = Counter(
            item.metadata.get("score", "unknown") for item in all_learnings
        )

        # Simple trend: ratio of recent good to bad
        recent = all_learnings[:20]
        good = sum(1 for item in recent if item.metadata.get("score") in ["excellent", "good"])
        total = len(recent)
        trend = "improving" if good > total / 2 else "stable" if good == total / 2 else "declining"

        return AdaptationStats(
            total_learnings=len(all_learnings),
            by_category=dict(by_category),
            recent_trend=trend,
        )
