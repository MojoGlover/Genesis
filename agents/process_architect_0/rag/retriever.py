# retriever.py
# THE RETRIEVER
#
# Responsibility:
#   Retrieves relevant context from the vector store given a query.
#
# What does NOT belong here:
#   - Raw datasets or embedded documents (those go in datasets/)
#   - Storage logic (that belongs in storage/)
#   - Evaluation logic (that belongs in evals/)

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RetrievedChunk:
    """A single chunk of context returned by a retrieval call."""

    def __init__(self, id: str, content: str, score: float, metadata: dict[str, Any] | None = None):
        self.id = id
        self.content = content
        self.score = score
        self.metadata = metadata or {}

    def __repr__(self) -> str:
        return f"RetrievedChunk(id={self.id!r}, score={self.score:.3f})"


class Retriever(ABC):
    """
    Abstract base class for context retrieval.

    A Retriever converts a query into an embedding, searches the
    VectorStore for nearest neighbors, and returns ranked chunks
    ready for injection into a prompt.

    Example agent implementation:
        class SemanticRetriever(Retriever):
            def __init__(self, embedding_router, vector_store):
                self._embed = embedding_router
                self._store = vector_store

            def retrieve(self, query, top_k=5):
                vec = self._embed.embed(query)
                hits = self._store.search(vec, top_k)
                return [RetrievedChunk(**h) for h in hits]
    """

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """
        Retrieve the most relevant stored chunks for the given query.

        Args:
            query: Natural language query string.
            top_k: Maximum number of chunks to return.

        Returns:
            Ordered list of RetrievedChunk objects, most relevant first.
        """

    def retrieve_as_text(self, query: str, top_k: int = 5) -> str:
        """
        Convenience method: retrieve and format results as a single string
        ready for prompt injection. Agents may override the formatting.
        """
        chunks = self.retrieve(query, top_k)
        if not chunks:
            return ""
        return "\n\n".join(f"[{i+1}] {c.content}" for i, c in enumerate(chunks))
