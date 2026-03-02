"""
modules/teacher/schemas.py — Pydantic request/response models for the Teacher module.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Learn ──────────────────────────────────────────────────────────────────────

class LearnRequest(BaseModel):
    """Ingest web knowledge about a topic into the knowledge base."""
    topic: str = Field(..., description="Topic to learn about")
    query: Optional[str] = Field(None, description="Search query (defaults to topic if omitted)")
    max_results: int = Field(8, ge=1, le=20, description="Max web results to ingest")
    min_tier: int = Field(2, ge=1, le=3, description="Min trust tier (1=official, 2=+community, 3=all)")
    min_grade: str = Field("C", description="Min source grade (A/B/C/D/F)")
    official_only: bool = Field(False, description="Restrict to Tier-1 official sources only")
    collection: str = Field("teacher_knowledge", description="Knowledge collection to store chunks in")


class SourceSummary(BaseModel):
    """Summary of a single source used during learning."""
    domain: str
    grade: str
    url: str
    title: str
    ingested: bool


class LearnResponse(BaseModel):
    topic: str
    chunks_stored: int
    sources_used: List[SourceSummary]
    sources_skipped: int
    collection: str
    message: str


# ── Ask ────────────────────────────────────────────────────────────────────────

class Citation(BaseModel):
    """A knowledge chunk used to construct an answer."""
    source: str
    title: str
    text: str
    score: float
    grade: str
    trust_tier: int


class AskRequest(BaseModel):
    """Ask the tutor a question."""
    question: str = Field(..., description="The question to answer")
    topic: Optional[str] = Field(None, description="Optional topic filter for RAG retrieval")
    search_fresh: bool = Field(False, description="Search web for fresh context before answering")
    max_context_chunks: int = Field(5, ge=1, le=10)
    collection: str = Field("teacher_knowledge", description="Knowledge collection to query")


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: List[Citation]
    context_chunks: int
    confidence: str  # high / medium / low
    used_web: bool


# ── Lesson ─────────────────────────────────────────────────────────────────────

class LessonRequest(BaseModel):
    """Generate a structured lesson on a topic."""
    topic: str = Field(..., description="Topic to cover")
    level: str = Field("beginner", description="beginner / intermediate / advanced")
    format: str = Field("outline", description="outline / detailed / quiz")
    collection: str = Field("teacher_knowledge", description="Knowledge collection to draw from")


class LessonResponse(BaseModel):
    topic: str
    level: str
    format: str
    content: str
    chunks_used: int


# ── Feedback ───────────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    """Provide quality feedback for a source domain."""
    domain: str = Field(..., description="Domain to rate (e.g. 'realpython.com')")
    accurate: bool = Field(..., description="Was the content accurate?")
    relevant: bool = Field(..., description="Was the content relevant to the topic?")
    notes: Optional[str] = Field(None, description="Optional human-readable notes")


class FeedbackResponse(BaseModel):
    domain: str
    grade_before: str
    grade_after: str
    flagged: bool
    message: str


# ── Disqualify ─────────────────────────────────────────────────────────────────

class DisqualifyRequest(BaseModel):
    domain: str = Field(..., description="Domain to permanently disqualify")
    reason: str = Field("", description="Reason for disqualification")


# ── Introspection ──────────────────────────────────────────────────────────────

class TopicsResponse(BaseModel):
    """Knowledge base size summary."""
    collections: Dict[str, int]   # collection_name → chunk_count
    total_chunks: int


class SourcesResponse(BaseModel):
    """Source quality ledger dump."""
    sources: List[Dict[str, Any]]
    total: int
    by_grade: Dict[str, int]
