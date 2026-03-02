"""
modules/teacher/tutor.py — Core teaching logic.

Handles:
  - Web knowledge ingestion (trusted sources → RAG store)
  - RAG-backed question answering with LLM synthesis
  - Structured lesson generation
  - Source quality feedback and ledger management
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from core.intelligence.rag.retriever import get_retriever
from core.tools.web_search import (
    search_trusted,
    search_official,
    result_to_chunk,
    get_source_ledger,
)

from .schemas import (
    AskRequest,
    AskResponse,
    Citation,
    DisqualifyRequest,
    FeedbackRequest,
    FeedbackResponse,
    LearnRequest,
    LearnResponse,
    LessonRequest,
    LessonResponse,
    SourceSummary,
    SourcesResponse,
    TopicsResponse,
)

logger = logging.getLogger(__name__)

# Grades we're willing to ingest into the knowledge base
_INGEST_GRADES = {"A", "B", "C"}
_HIGH_CONFIDENCE_GRADES = {"A", "B"}

# All teacher-owned Qdrant collections
_ALL_COLLECTIONS = [
    "teacher_knowledge",
    "curriculum_content",
    "agent_skills",
    "persona_traits",
]


def _answer_confidence(citations: List[Citation]) -> str:
    """Derive overall answer confidence from citation scores and grades."""
    if not citations:
        return "low"
    avg_score = sum(c.score for c in citations) / len(citations)
    high_grade_count = sum(1 for c in citations if c.grade in _HIGH_CONFIDENCE_GRADES)
    if avg_score >= 0.78 and high_grade_count >= max(1, len(citations) // 2):
        return "high"
    if avg_score >= 0.62:
        return "medium"
    return "low"


class Tutor:
    """
    Core teaching engine.

    Lazy-initialises all external dependencies (RAG store, source ledger,
    Anthropic client) so startup is fast even if services are temporarily down.
    """

    def __init__(self) -> None:
        self._retriever = None
        self._ledger = None
        self._llm: Any = None
        self._llm_available: Optional[bool] = None  # None=unknown, True/False after first try

    # ── Lazy accessors ─────────────────────────────────────────────────────────

    @property
    def retriever(self):
        if self._retriever is None:
            self._retriever = get_retriever()
        return self._retriever

    @property
    def ledger(self):
        if self._ledger is None:
            self._ledger = get_source_ledger()
        return self._ledger

    def _get_llm(self):
        """Return Anthropic AsyncAnthropic client, or None if unavailable."""
        if self._llm_available is False:
            return None
        if self._llm is not None:
            return self._llm
        try:
            import anthropic
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                logger.warning("[teacher] ANTHROPIC_API_KEY not set — LLM generation disabled")
                self._llm_available = False
                return None
            self._llm = anthropic.AsyncAnthropic(api_key=key)
            self._llm_available = True
            logger.info("[teacher] Anthropic client initialised")
            return self._llm
        except ImportError:
            logger.warning("[teacher] `anthropic` package not installed — LLM generation disabled")
            self._llm_available = False
            return None
        except Exception as exc:
            logger.error("[teacher] Failed to init Anthropic client: %s", exc)
            self._llm_available = False
            return None

    # ── Learn ──────────────────────────────────────────────────────────────────

    async def learn(self, req: LearnRequest) -> LearnResponse:
        """Search trusted web sources and ingest chunks into the knowledge base."""
        query = req.query or req.topic
        logger.info("[teacher] learn: topic='%s' query='%s' tier=%d", req.topic, query, req.min_tier)

        # ── Fetch results from web ──────────────────────────────────────────
        try:
            if req.official_only:
                results = search_official(query, max_results=req.max_results)
            else:
                results = search_trusted(
                    query,
                    max_results=req.max_results,
                    min_tier=req.min_tier,
                    min_grade=req.min_grade,
                )
        except Exception as exc:
            logger.error("[teacher] web search failed for '%s': %s", req.topic, exc)
            return LearnResponse(
                topic=req.topic,
                chunks_stored=0,
                sources_used=[],
                sources_skipped=0,
                collection=req.collection,
                message=f"Web search error: {exc}",
            )

        sources_used: List[SourceSummary] = []
        sources_skipped = 0
        chunks_stored = 0

        for result in results:
            summary = SourceSummary(
                domain=result.domain,
                grade=result.grade,
                url=result.url,
                title=result.title,
                ingested=False,
            )

            # Skip low-quality sources
            if result.grade not in _INGEST_GRADES:
                sources_skipped += 1
                sources_used.append(summary)
                continue

            try:
                chunk_meta = result_to_chunk(result, topic=req.topic, chunk_type="concept")
                self.retriever.store(
                    text=result.snippet,
                    metadata=chunk_meta,
                    collection=req.collection,
                )
                summary.ingested = True
                chunks_stored += 1
                # Reward the source for being usable
                self.ledger.record_use(domain=result.domain, accurate=True, relevant=True)
            except Exception as exc:
                logger.error("[teacher] store failed for %s: %s", result.url, exc)

            sources_used.append(summary)

        logger.info(
            "[teacher] learned '%s': stored=%d sources=%d skipped=%d",
            req.topic, chunks_stored, len(sources_used), sources_skipped,
        )

        return LearnResponse(
            topic=req.topic,
            chunks_stored=chunks_stored,
            sources_used=sources_used,
            sources_skipped=sources_skipped,
            collection=req.collection,
            message=(
                f"Stored {chunks_stored} chunk(s) about '{req.topic}' "
                f"from {len(sources_used)} source(s)."
            ),
        )

    # ── Ask ────────────────────────────────────────────────────────────────────

    async def ask(self, req: AskRequest) -> AskResponse:
        """Answer a question using RAG context and optional LLM synthesis."""
        logger.info("[teacher] ask: '%s'", req.question)

        used_web = False
        filters = {"topic": req.topic} if req.topic else None

        # ── 1. Primary RAG retrieval ────────────────────────────────────────
        chunks = self._retrieve(
            query=req.question,
            collection=req.collection,
            limit=req.max_context_chunks,
            filters=filters,
        )

        # ── 2. Web top-up if thin context or explicitly requested ───────────
        if req.search_fresh or len(chunks) < 2:
            try:
                fresh = search_trusted(
                    req.question,
                    max_results=5,
                    min_tier=2,
                    min_grade="B",
                )
                for r in fresh[:3]:
                    if r.grade in _HIGH_CONFIDENCE_GRADES:
                        meta = result_to_chunk(
                            r,
                            topic=req.topic or "general",
                            chunk_type="concept",
                        )
                        self.retriever.store(
                            text=r.snippet,
                            metadata=meta,
                            collection=req.collection,
                        )
                        self.ledger.record_use(r.domain, accurate=True, relevant=True)
                used_web = True

                # Re-retrieve with fresh data in place
                chunks = self._retrieve(
                    query=req.question,
                    collection=req.collection,
                    limit=req.max_context_chunks,
                    filters=filters,
                )
            except Exception as exc:
                logger.warning("[teacher] web top-up failed: %s", exc)

        # ── 3. Build citations ──────────────────────────────────────────────
        citations = [
            Citation(
                source=c.source,
                title=c.metadata.get("title", c.source),
                text=c.text[:300],
                score=round(c.score, 3),
                grade=c.metadata.get("grade", "?"),
                trust_tier=c.trust_tier,
            )
            for c in chunks
        ]

        # ── 4. Generate answer ──────────────────────────────────────────────
        if chunks:
            context = self.retriever.build_context(
                query=req.question,
                collection=req.collection,
                limit=req.max_context_chunks,
                max_chars=3000,
            )
            answer = await self._llm_answer(req.question, context)
        else:
            answer = (
                "I don't have enough knowledge on this topic yet. "
                "Use POST /teacher/learn to ingest relevant material first."
            )

        return AskResponse(
            question=req.question,
            answer=answer,
            citations=citations,
            context_chunks=len(chunks),
            confidence=_answer_confidence(citations),
            used_web=used_web,
        )

    def _retrieve(self, query: str, collection: str, limit: int, filters):
        """Safe wrapper around retriever.retrieve()."""
        try:
            return self.retriever.retrieve(
                query=query,
                collection=collection,
                limit=limit,
                threshold=0.55,
                filters=filters,
            )
        except Exception as exc:
            logger.error("[teacher] RAG retrieval failed: %s", exc)
            return []

    async def _llm_answer(self, question: str, context: str) -> str:
        """Call LLM with RAG context to generate a grounded answer.

        Falls back to a context excerpt if the LLM is unavailable.
        """
        client = self._get_llm()
        if client is None:
            return (
                "Based on available reference material:\n\n"
                + context[:1500]
                + "\n\n"
                + "*(LLM unavailable — set ANTHROPIC_API_KEY and install the "
                "`anthropic` package to enable AI-generated answers)*"
            )

        system = (
            "You are an expert AI tutor. Answer the student's question clearly and "
            "accurately using ONLY the provided reference material. Cite your sources "
            "by mentioning where information came from. If the references don't fully "
            "answer the question, say so and explain what you do know. "
            "Be concise, accurate, and educational."
        )
        user_msg = f"Reference material:\n{context}\n\nStudent question: {question}"

        try:
            response = await client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            return response.content[0].text
        except Exception as exc:
            logger.error("[teacher] LLM answer generation failed: %s", exc)
            return (
                "Based on available reference material:\n\n"
                + context[:1500]
                + f"\n\n*(LLM error: {exc})*"
            )

    # ── Lesson ─────────────────────────────────────────────────────────────────

    async def lesson(self, req: LessonRequest) -> LessonResponse:
        """Generate a structured lesson using RAG context + LLM."""
        logger.info("[teacher] lesson: topic='%s' level=%s format=%s", req.topic, req.level, req.format)

        context = self.retriever.build_context(
            query=f"{req.topic} {req.level}",
            collection=req.collection,
            limit=8,
            max_chars=4000,
        )

        format_instruction = {
            "outline":  "Create a concise lesson outline with key concepts and subtopics.",
            "detailed": "Create a detailed lesson with explanations, examples, and takeaways.",
            "quiz":     "Create a 5-question quiz with answers to test understanding of the topic.",
        }.get(req.format, "Create a lesson outline.")

        client = self._get_llm()
        if client is None:
            content = (
                f"# {req.topic.title()} — {req.level.title()} Level\n\n"
                "*(LLM unavailable — context preview below)*\n\n"
                + context[:2000]
            )
            return LessonResponse(
                topic=req.topic,
                level=req.level,
                format=req.format,
                content=content,
                chunks_used=0,
            )

        system = (
            f"You are an expert educator creating a {req.level}-level lesson. "
            f"{format_instruction} "
            "Use the reference material provided. Be clear, accurate, and engaging. "
            "Structure the output with markdown headings."
        )
        user_msg = (
            f"Reference material:\n{context}\n\n"
            f"Create a {req.level} {req.format} lesson about: {req.topic}"
        )

        try:
            response = await client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            content = response.content[0].text
        except Exception as exc:
            logger.error("[teacher] lesson generation failed: %s", exc)
            content = (
                f"Lesson generation failed: {exc}\n\n"
                "Context preview:\n" + context[:2000]
            )

        return LessonResponse(
            topic=req.topic,
            level=req.level,
            format=req.format,
            content=content,
            chunks_used=min(8, self.retriever.collection_size(req.collection)),
        )

    # ── Feedback ───────────────────────────────────────────────────────────────

    def feedback(self, req: FeedbackRequest) -> FeedbackResponse:
        """Record source quality feedback and update the domain's running grade."""
        before_summary = self.ledger.get_domain_summary(req.domain)
        grade_before = before_summary.get("grade", "?")

        new_grade = self.ledger.record_use(
            domain=req.domain,
            accurate=req.accurate,
            relevant=req.relevant,
        )

        after_summary = self.ledger.get_domain_summary(req.domain)
        flagged = bool(after_summary.get("flagged", False))

        grade_after = new_grade.value if hasattr(new_grade, "value") else str(new_grade)
        changed = grade_before != grade_after

        return FeedbackResponse(
            domain=req.domain,
            grade_before=grade_before,
            grade_after=grade_after,
            flagged=flagged,
            message=(
                f"Grade {'changed: ' + grade_before + ' → ' + grade_after if changed else 'unchanged: ' + grade_after}"
                + (" [FLAGGED for review]" if flagged else "")
                + (f" — {req.notes}" if req.notes else "")
            ),
        )

    def disqualify(self, req: DisqualifyRequest) -> Dict[str, Any]:
        """Permanently disqualify a domain from ever being served."""
        self.ledger.disqualify_domain(req.domain, reason=req.reason)
        return {
            "domain": req.domain,
            "grade": "F",
            "message": f"Domain '{req.domain}' disqualified. Reason: {req.reason or '(none)'}",
        }

    # ── Introspection ──────────────────────────────────────────────────────────

    def get_topics(self) -> TopicsResponse:
        """Return chunk counts per knowledge collection."""
        collections: Dict[str, int] = {}
        try:
            for col in _ALL_COLLECTIONS:
                size = self.retriever.collection_size(col)
                if size > 0:
                    collections[col] = size
        except Exception as exc:
            logger.error("[teacher] get_topics error: %s", exc)

        return TopicsResponse(
            collections=collections,
            total_chunks=sum(collections.values()),
        )

    def get_sources(self) -> SourcesResponse:
        """Return all source domains with their grades from the ledger."""
        try:
            all_records = self.ledger.get_all_grades()
            by_grade: Dict[str, int] = {}
            for rec in all_records:
                g = rec.get("current_grade", "?")
                by_grade[g] = by_grade.get(g, 0) + 1
        except Exception as exc:
            logger.error("[teacher] get_sources error: %s", exc)
            all_records = []
            by_grade = {}

        return SourcesResponse(
            sources=all_records,
            total=len(all_records),
            by_grade=by_grade,
        )

    def health(self) -> Dict[str, Any]:
        """Return health of all teacher subsystems."""
        rag_status: Dict[str, Any] = {"status": "unavailable"}
        try:
            rag_status = self.retriever.health()
        except Exception as exc:
            rag_status = {"status": "error", "detail": str(exc)}

        return {
            "rag": rag_status,
            "llm_available": self._llm_available,
            "ledger": "ok",
        }
