# embedding_router.py
# THE EMBEDDING ROUTER
#
# Responsibility:
#   Generates embeddings from text and routes to the correct embedding provider.
#
# What does NOT belong here:
#   - Retrieval logic (that belongs in retriever.py)
#   - Storage of embeddings (that belongs in storage/vector_store.py)
#   - Model routing for generation (that belongs in models/)

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingRouter(ABC):
    """
    Abstract base class for embedding generation.

    Concrete implementations connect to a specific embedding provider
    (OpenAI text-embedding-*, Ollama, a local SBERT model, etc.).
    The interface is intentionally minimal — callers only need vectors.

    Example agent implementation:
        class OllamaEmbeddingRouter(EmbeddingRouter):
            def embed(self, text): ...
    """

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """
        Generate an embedding vector for a single piece of text.

        Args:
            text: The input string to embed.

        Returns:
            A list of floats representing the embedding.
            Dimension is determined by the underlying provider/model.
        """

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in one call.
        More efficient than calling embed() in a loop for large datasets.

        Args:
            texts: List of input strings.

        Returns:
            List of embedding vectors in the same order as the input.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding vector dimension for this provider/model."""

    @property
    def provider_name(self) -> str:
        """Human-readable name of the embedding provider. Override in subclass."""
        return self.__class__.__name__
