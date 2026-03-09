"""Quality checks for agent execution and outputs."""

from typing import Any

from pydantic import BaseModel

from ai_starter.core.state import Reflection, Step, StepResult, TickResult


class QualityMetrics(BaseModel):
    """Quality metrics for agent execution."""
    success_rate: float
    avg_latency_ms: int
    error_rate: float
    learning_rate: float  # New learnings per task
    overall_score: float  # 0.0 to 1.0


class QualityChecker:
    """Checks quality of agent execution and outputs."""

    @staticmethod
    def check_step_quality(step: Step, result: StepResult) -> float:
        """Check quality of a single step execution (0.0 to 1.0)."""
        score = 1.0
        
        # Deduct for failures
        if not result.success:
            score -= 0.5
        
        # Deduct for errors
        if result.error:
            score -= 0.2
        
        # Deduct for very long execution
        if result.duration_ms > 30000:  # > 30 seconds
            score -= 0.1
        
        # Deduct for empty output
        if not result.output:
            score -= 0.2
        
        return max(0.0, score)

    @staticmethod
    def check_reflection_quality(reflection: Reflection) -> float:
        """Check quality of reflection (0.0 to 1.0)."""
        score = 1.0
        
        # Deduct if failed
        if not reflection.success:
            score -= 0.3
        
        # Deduct if no learnings
        if not reflection.learnings:
            score -= 0.2
        
        # Deduct if summary is too short
        if len(reflection.summary) < 10:
            score -= 0.2
        
        # Bonus for good learnings
        if len(reflection.learnings) >= 3:
            score += 0.1
        
        return min(1.0, max(0.0, score))

    @staticmethod
    def calculate_metrics(history: list[TickResult]) -> QualityMetrics:
        """Calculate aggregate quality metrics from execution history."""
        if not history:
            return QualityMetrics(
                success_rate=0.0,
                avg_latency_ms=0,
                error_rate=1.0,
                learning_rate=0.0,
                overall_score=0.0,
            )
        
        successes = sum(1 for t in history if t.reflection.success)
        total_learnings = sum(len(t.reflection.learnings) for t in history)
        total_latency = sum(t.duration_ms for t in history)
        
        success_rate = successes / len(history)
        error_rate = 1.0 - success_rate
        avg_latency_ms = total_latency // len(history)
        learning_rate = total_learnings / len(history)
        
        # Overall score combines metrics
        overall_score = (
            success_rate * 0.4 +
            (1.0 - min(1.0, avg_latency_ms / 10000)) * 0.2 +
            min(1.0, learning_rate / 3.0) * 0.4
        )
        
        return QualityMetrics(
            success_rate=success_rate,
            avg_latency_ms=avg_latency_ms,
            error_rate=error_rate,
            learning_rate=learning_rate,
            overall_score=overall_score,
        )
