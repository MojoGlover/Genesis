# indexer.py
# THE INDEXER
#
# Responsibility:
#   Processes and indexes documents or data into the vector store.
#
# What does NOT belong here:
#   - Retrieval logic (that belongs in retriever.py)
#   - Raw datasets (those go in datasets/)
#   - Evaluation logic (that belongs in evals/)

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Indexer(ABC):
    """
    Abstract base class for document indexing.

    An Indexer takes raw content, chunks it, embeds it via EmbeddingRouter,
    and persists it via VectorStore. Agents subclass this to control
    chunking strategy and indexing pipeline.

    Example agent implementation:
        class SentenceChunkIndexer(Indexer):
            def index_document(self, doc_id, content, metadata): ...
    """

    @abstractmethod
    def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        """
        Chunk, embed, and store a single document.

        Args:
            doc_id:   Stable identifier for this document (used for updates/deletes).
            content:  The full text content to index.
            metadata: Optional payload stored with every chunk (e.g. source URL, date).

        Returns:
            List of chunk IDs that were stored in the vector store.
        """

    @abstractmethod
    def remove_document(self, doc_id: str) -> bool:
        """
        Remove all indexed chunks for the given document ID.

        Returns True if any chunks were found and removed, False if doc_id unknown.
        """

    def index_dataset(self, path: str) -> int:
        """
        Batch-index all documents found at the given dataset path.
        Agents may override with an efficient bulk-loading strategy.
        Default: not supported.

        Returns the number of documents indexed.
        """
        raise NotImplementedError("index_dataset() not implemented by this Indexer")
