"""Self-improvement schemas."""

from enum import Enum

from pydantic import BaseModel, Field


class EvalScore(str, Enum):
    """Task execution evaluation scores."""
    excellent = "excellent"
    good = "good"
    adequate = "adequate"
    poor = "poor"
    failed = "failed"


class EvalReport(BaseModel):
    """Self-evaluation report for a task execution."""
    score: EvalScore
    reasoning: str
    learnings: list[str] = Field(default_factory=list)
    suggested_improvements: list[str] = Field(default_factory=list)


class AdaptationStats(BaseModel):
    """Statistics on behavioral adaptations."""
    total_learnings: int
    by_category: dict[str, int] = Field(default_factory=dict)
    recent_trend: str = ""
