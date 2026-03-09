"""Self-evaluation and learning extraction."""

from ai_starter.core.identity import Identity
from ai_starter.core.state import TickResult
from ai_starter.improvement.schemas import EvalReport, EvalScore
from ai_starter.llm.client import OllamaClient
from ai_starter.llm.response_parser import extract_json
from ai_starter.llm.schemas import Message
from ai_starter.memory.schemas import MemoryCategory, MemoryItem
from ai_starter.memory.storage import MemoryStore


class SelfEvaluator:
    """Evaluates task execution and extracts learnings."""

    def __init__(
        self,
        llm: OllamaClient,
        memory: MemoryStore,
        identity: Identity,
    ):
        self.llm = llm
        self.memory = memory
        self.identity = identity

    async def evaluate(self, tick: TickResult) -> EvalReport:
        """Evaluate a single task execution."""
        prompt = f"""You are {self.identity.name}.

Task executed: {tick.task.description}
Success: {tick.reflection.success}
Summary: {tick.reflection.summary}
Duration: {tick.duration_ms}ms

Evaluate this execution on a scale: excellent, good, adequate, poor, failed.

Respond in JSON:
{{
  "score": "excellent|good|adequate|poor|failed",
  "reasoning": "why this score",
  "learnings": ["learning 1", "learning 2"],
  "suggested_improvements": ["improvement 1"]
}}"""

        response = await self.llm.generate([Message(role="user", content=prompt)])
        data = extract_json(response.content)

        if not data:
            return EvalReport(
                score=EvalScore.adequate,
                reasoning="Failed to parse evaluation",
                learnings=[],
                suggested_improvements=[],
            )

        return EvalReport(
            score=EvalScore(data.get("score", "adequate")),
            reasoning=data.get("reasoning", ""),
            learnings=data.get("learnings", []),
            suggested_improvements=data.get("suggested_improvements", []),
        )

    async def periodic_review(self, last_n: int = 20) -> EvalReport:
        """Review recent task history for patterns."""
        recent = self.memory.get_recent(limit=last_n, category=MemoryCategory.task_result)

        if not recent:
            return EvalReport(
                score=EvalScore.adequate,
                reasoning="No history to review",
                learnings=[],
                suggested_improvements=[],
            )

        summary = "\n".join(f"- {m.content}" for m in recent)

        prompt = f"""Review the last {len(recent)} tasks:

{summary}

What patterns do you see? What should we improve?

Respond in JSON:
{{
  "score": "excellent|good|adequate|poor|failed",
  "reasoning": "overall assessment",
  "learnings": ["pattern 1", "pattern 2"],
  "suggested_improvements": ["improvement 1"]
}}"""

        response = await self.llm.generate([Message(role="user", content=prompt)])
        data = extract_json(response.content)

        if not data:
            return EvalReport(
                score=EvalScore.adequate,
                reasoning="Failed to parse review",
                learnings=[],
                suggested_improvements=[],
            )

        return EvalReport(
            score=EvalScore(data.get("score", "adequate")),
            reasoning=data.get("reasoning", ""),
            learnings=data.get("learnings", []),
            suggested_improvements=data.get("suggested_improvements", []),
        )

    def store_learnings(self, report: EvalReport) -> None:
        """Save learnings to memory."""
        for learning in report.learnings:
            self.memory.store(
                MemoryItem(
                    category=MemoryCategory.learning,
                    content=learning,
                    metadata={"score": report.score.value},
                )
            )
