"""
modules/teacher/module.py — GENESIS General AI Tutor module.

Auto-discovered by GENESIS ModuleRegistry at startup.

Endpoints:
    POST  /teacher/learn     — ingest trusted web knowledge about a topic
    POST  /teacher/ask       — ask a question (RAG + LLM answer with citations)
    POST  /teacher/lesson    — generate a structured lesson (outline/detailed/quiz)
    POST  /teacher/feedback  — rate a source domain's accuracy/relevance
    POST  /teacher/disqualify — permanently ban a domain from being served
    GET   /teacher/topics    — knowledge base chunk counts per collection
    GET   /teacher/sources   — full source quality ledger
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from core.modules.base import ModuleBase
from .schemas import (
    AskRequest,
    AskResponse,
    DisqualifyRequest,
    FeedbackRequest,
    FeedbackResponse,
    LearnRequest,
    LearnResponse,
    LessonRequest,
    LessonResponse,
    SourcesResponse,
    TopicsResponse,
)
from .tutor import Tutor

logger = logging.getLogger(__name__)


class Module(ModuleBase):
    """GENESIS General AI Tutor.

    Ingests knowledge from trusted web sources into a Qdrant-backed RAG store,
    then answers questions using retrieved context and LLM synthesis.
    Sources are graded continuously — every use updates their accuracy score.
    """

    def __init__(self) -> None:
        self._tutor = Tutor()
        self._request_count = 0
        self._error_count = 0
        self._learn_count = 0
        self._ask_count = 0
        self._lesson_count = 0

    # ── ModuleBase contract ────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "teacher"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return (
            "General AI Tutor — ingests trusted web knowledge, answers questions "
            "with RAG citations, generates lessons, and grades sources continuously."
        )

    @property
    def tags(self) -> List[str]:
        return ["teacher", "tutor", "knowledge", "rag"]

    @property
    def router(self) -> APIRouter:
        r = APIRouter(prefix="/teacher", tags=self.tags)

        # ── POST /teacher/learn ────────────────────────────────────────────
        @r.post(
            "/learn",
            response_model=LearnResponse,
            summary="Ingest knowledge about a topic from trusted web sources",
        )
        async def learn(req: LearnRequest):
            """
            Search the web for trusted material on a topic and store it in the
            RAG knowledge base. Sources are graded by trust tier; only A/B/C
            grade sources are ingested. Each ingested source's grade is updated
            in the persistent ledger.
            """
            try:
                self._request_count += 1
                self._learn_count += 1
                return await self._tutor.learn(req)
            except Exception as exc:
                self._error_count += 1
                logger.error("[teacher] /learn error: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /teacher/ask ──────────────────────────────────────────────
        @r.post(
            "/ask",
            response_model=AskResponse,
            summary="Ask a question — answered from the RAG knowledge base",
        )
        async def ask(req: AskRequest):
            """
            Ask a question. The tutor retrieves semantically relevant chunks
            from the knowledge base and uses an LLM to synthesise a grounded
            answer with citations. Optionally fetches fresh web context first.
            """
            try:
                self._request_count += 1
                self._ask_count += 1
                return await self._tutor.ask(req)
            except Exception as exc:
                self._error_count += 1
                logger.error("[teacher] /ask error: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /teacher/lesson ───────────────────────────────────────────
        @r.post(
            "/lesson",
            response_model=LessonResponse,
            summary="Generate a structured lesson on a topic",
        )
        async def lesson(req: LessonRequest):
            """
            Generate an outline, detailed lesson, or quiz on a topic using
            the knowledge base as source material and an LLM for generation.
            """
            try:
                self._request_count += 1
                self._lesson_count += 1
                return await self._tutor.lesson(req)
            except Exception as exc:
                self._error_count += 1
                logger.error("[teacher] /lesson error: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /teacher/feedback ─────────────────────────────────────────
        @r.post(
            "/feedback",
            response_model=FeedbackResponse,
            summary="Rate a source domain's accuracy and relevance",
        )
        async def feedback(req: FeedbackRequest):
            """
            Record accuracy/relevance feedback for a domain. Updates the
            domain's running accuracy score and grade in the persistent
            source ledger. Domains that fall below threshold are auto-flagged.
            """
            try:
                self._request_count += 1
                return self._tutor.feedback(req)
            except Exception as exc:
                self._error_count += 1
                logger.error("[teacher] /feedback error: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── POST /teacher/disqualify ───────────────────────────────────────
        @r.post(
            "/disqualify",
            summary="Permanently disqualify a domain (grade → F)",
        )
        async def disqualify(req: DisqualifyRequest):
            """
            Permanently set a domain's grade to F. It will never be returned
            in search results again. Use when a domain has produced
            consistently hallucinated or harmful content.
            """
            try:
                self._request_count += 1
                return self._tutor.disqualify(req)
            except Exception as exc:
                self._error_count += 1
                logger.error("[teacher] /disqualify error: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /teacher/topics ────────────────────────────────────────────
        @r.get(
            "/topics",
            response_model=TopicsResponse,
            summary="Knowledge base chunk counts per collection",
        )
        async def topics():
            """Show how many knowledge chunks are stored per Qdrant collection."""
            try:
                return self._tutor.get_topics()
            except Exception as exc:
                logger.error("[teacher] /topics error: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        # ── GET /teacher/sources ───────────────────────────────────────────
        @r.get(
            "/sources",
            response_model=SourcesResponse,
            summary="Full source quality ledger",
        )
        async def sources():
            """
            List all tracked source domains with their current grade,
            accuracy score, use count, and flagged status.
            """
            try:
                return self._tutor.get_sources()
            except Exception as exc:
                logger.error("[teacher] /sources error: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc))

        return r

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def on_startup(self) -> None:
        logger.info(
            "[teacher] module ready — "
            "POST /teacher/learn | POST /teacher/ask | POST /teacher/lesson | "
            "POST /teacher/feedback | POST /teacher/disqualify | "
            "GET /teacher/topics | GET /teacher/sources"
        )

    async def on_shutdown(self) -> None:
        logger.info(
            "[teacher] shutdown — requests=%d learn=%d ask=%d lesson=%d errors=%d",
            self._request_count,
            self._learn_count,
            self._ask_count,
            self._lesson_count,
            self._error_count,
        )

    # ── Health ─────────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        tutor_health = self._tutor.health()
        return {
            "status": "ok",
            "module": self.name,
            "version": self.version,
            "request_count": self._request_count,
            "error_count": self._error_count,
            "learn_count": self._learn_count,
            "ask_count": self._ask_count,
            "lesson_count": self._lesson_count,
            **tutor_health,
        }
