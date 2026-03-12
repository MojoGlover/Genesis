# vector_store.py
# VECTOR STORAGE ADAPTER
#
# Responsibility:
#   Handles vector/embedding storage and similarity search.
#
# What does NOT belong here:
#   - Embedding generation logic (that belongs in rag/)
#   - SQLite persistence (that belongs in sqlite_store.py)
#   - Memory business logic (that belongs in memory/)

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    """
    Abstract base class for vector/embedding storage backends.

    Agents may implement this against any backend: Qdrant, Chroma,
    FAISS, Weaviate, or a plain in-memory list. The interface stays
    constant regardless of backend so callers never care which one is used.

    Example agent implementation:
        class InMemoryVectorStore(VectorStore):
            def __init__(self):
                self._store = {}   # id -> {"vector": [...], "metadata": {...}}

            def upsert(self, id, vector, metadata=None):
                self._store[id] = {"vector": vector, "metadata": metadata or {}}
    """

    @abstractmethod
    def upsert(self, id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        """
        Insert or replace a vector entry.

        Args:
            id:       Unique identifier for this vector (typically MemoryRecord.id).
            vector:   The embedding as a list of floats.
            metadata: Optional payload stored alongside the vector.
        """

    @abstractmethod
    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """
        Find the top_k most similar vectors by cosine or dot-product similarity.

        Returns:
            List of result dicts, each containing at minimum:
                {"id": str, "score": float, "metadata": dict}
            Ordered from most to least similar.
        """

    @abstractmethod
    def delete(self, id: str) -> bool:
        """
        Remove a vector by ID.
        Returns True if the entry existed and was deleted, False otherwise.
        """

    @abstractmethod
    def count(self) -> int:
        """Return the total number of vectors currently stored."""

    def clear(self) -> None:
        """Remove all vectors. Agents may override; default: not supported."""
        raise NotImplementedError("clear() not implemented by this VectorStore")
