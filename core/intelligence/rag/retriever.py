"""
core/intelligence/rag/retriever.py — Retrieval-Augmented Generation layer

Unified interface for storing and retrieving knowledge chunks from Qdrant.
Supports multiple named collections so modules keep their knowledge isolated.

Collections used by the teacher system:
    "teacher_knowledge"   — general tutor knowledge (web + LLM sourced)
    "curriculum_content"  — structured lesson content
    "agent_skills"        — capabilities taught to AI agents
    "persona_traits"      — voice, tone, personality calibration data

Usage:
    from core.intelligence.rag.retriever import get_retriever

    r = get_retriever()

    # Store a chunk
    chunk_id = r.store(
        text="Python uses indentation to define code blocks.",
        metadata={
            "source":      "https://docs.python.org/3/tutorial/",
            "trust_tier":  1,
            "topic":       "python",
            "type":        "concept",
            "confidence":  "high",
        },
        collection="teacher_knowledge",
    )

    # Retrieve relevant chunks for a query
    chunks = r.retrieve(
        query="how does Python handle code blocks?",
        collection="teacher_knowledge",
        limit=5,
    )
    for chunk in chunks:
        print(chunk.text, chunk.score, chunk.source)

    # Build a context block ready to inject into an LLM prompt
    context = r.build_context(
        query="explain Python indentation",
        collection="teacher_knowledge",
    )
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Vector dimension for all-mpnet-base-v2
_VECTOR_SIZE = 768


# ── Pydantic models ──────────────────────────────────────────────────────────

class KnowledgeChunk(BaseModel):
    """A single retrieved knowledge chunk."""
    chunk_id:   str
    text:       str
    score:      float = 0.0
    source:     str   = ""
    trust_tier: int   = 2         # 1=high, 2=medium, 3=low
    confidence: str   = "medium"  # "high" | "medium" | "low"
    topic:      str   = ""
    chunk_type: str   = "fact"    # "concept" | "fact" | "example" | "procedure"
    metadata:   Dict[str, Any] = Field(default_factory=dict)


class StoreResult(BaseModel):
    chunk_id:    str
    collection:  str
    text_length: int


# ── RAGRetriever ─────────────────────────────────────────────────────────────

class RAGRetriever:
    """
    Multi-collection RAG store backed by Qdrant.

    Thread-safe for reads. Writes are not synchronized — call from a single
    thread or use your own locking when writing concurrently.
    """

    def __init__(self, qdrant_url: str = "http://localhost:6333"):
        self._url        = qdrant_url
        self._client     = None   # lazy — imported in _get_client()
        self._embedder   = None   # lazy — imported in _get_embedder()
        self._collections: set[str] = set()

    # ── Lazy init ─────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(self._url)
            logger.info(f"[RAGRetriever] Connected to Qdrant at {self._url}")
        return self._client

    def _get_embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            device = _pick_device()
            self._embedder = SentenceTransformer("all-mpnet-base-v2", device=device)
            logger.info(f"[RAGRetriever] Embedder loaded on {device}")
        return self._embedder

    def _embed(self, text: str) -> List[float]:
        return self._get_embedder().encode(text).tolist()

    # ── Collection management ─────────────────────────────────────────────────

    def _ensure_collection(self, name: str) -> None:
        """Create Qdrant collection if it doesn't exist yet."""
        if name in self._collections:
            return

        from qdrant_client.models import Distance, VectorParams

        client = self._get_client()
        existing = {c.name for c in client.get_collections().collections}

        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
            )
            logger.info(f"[RAGRetriever] Created collection '{name}'")

        self._collections.add(name)

    def list_collections(self) -> List[str]:
        """Return all Qdrant collections managed by this retriever."""
        client = self._get_client()
        return [c.name for c in client.get_collections().collections]

    def collection_size(self, collection: str) -> int:
        """Return number of chunks stored in a collection."""
        try:
            self._ensure_collection(collection)
            info = self._get_client().get_collection(collection)
            return info.points_count or 0
        except Exception as exc:
            logger.warning(f"[RAGRetriever] Could not get size of '{collection}': {exc}")
            return 0

    # ── Storage ───────────────────────────────────────────────────────────────

    def store(
        self,
        text:       str,
        metadata:   Optional[Dict[str, Any]] = None,
        collection: str = "teacher_knowledge",
    ) -> str:
        """
        Embed and store a single text chunk.

        Args:
            text:       The knowledge text to store.
            metadata:   Any fields: source, trust_tier, topic, type, confidence, etc.
            collection: Target Qdrant collection name.

        Returns:
            chunk_id (UUID string)

        Raises:
            ValueError: If text is empty.
            RuntimeError: If Qdrant is unreachable.
        """
        if not text or not text.strip():
            raise ValueError("text must not be empty")

        self._ensure_collection(collection)

        chunk_id  = str(uuid.uuid4())
        embedding = self._embed(text)
        payload   = {"text": text, **(metadata or {})}

        from qdrant_client.models import PointStruct

        self._get_client().upsert(
            collection_name=collection,
            points=[PointStruct(id=chunk_id, vector=embedding, payload=payload)],
        )

        logger.debug(
            f"[RAGRetriever] Stored chunk {chunk_id[:8]}... "
            f"in '{collection}' ({len(text)} chars)"
        )
        return chunk_id

    def store_batch(
        self,
        items:      List[Dict[str, Any]],
        collection: str = "teacher_knowledge",
    ) -> List[str]:
        """
        Store multiple chunks efficiently.

        Args:
            items: List of dicts, each with required key "text" plus any metadata.
            collection: Target collection.

        Returns:
            List of chunk_ids in same order as input.
        """
        if not items:
            return []

        self._ensure_collection(collection)

        from qdrant_client.models import PointStruct

        embedder = self._get_embedder()
        texts    = [item["text"] for item in items]
        vectors  = embedder.encode(texts).tolist()

        points   = []
        ids      = []
        for item, vector in zip(items, vectors):
            cid     = str(uuid.uuid4())
            payload = {k: v for k, v in item.items()}
            points.append(PointStruct(id=cid, vector=vector, payload=payload))
            ids.append(cid)

        self._get_client().upsert(collection_name=collection, points=points)

        logger.info(
            f"[RAGRetriever] Stored {len(ids)} chunks in '{collection}'"
        )
        return ids

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query:       str,
        collection:  str = "teacher_knowledge",
        limit:       int = 5,
        threshold:   float = 0.60,
        filters:     Optional[Dict[str, Any]] = None,
    ) -> List[KnowledgeChunk]:
        """
        Semantic search for the most relevant chunks.

        Args:
            query:      Natural-language question or topic.
            collection: Which Qdrant collection to search.
            limit:      Max results to return.
            threshold:  Minimum cosine similarity score (0.0–1.0).
            filters:    Optional exact-match filters on metadata fields,
                        e.g. {"topic": "python", "trust_tier": 1}.

        Returns:
            List of KnowledgeChunk sorted by relevance (highest first).
        """
        if not query or not query.strip():
            return []

        self._ensure_collection(collection)

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        qfilter = None
        if filters:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filters.items()
            ]
            qfilter = Filter(must=conditions)

        query_vec = self._embed(query)

        try:
            results = self._get_client().query_points(
                collection_name=collection,
                query=query_vec,
                limit=limit,
                score_threshold=threshold,
                query_filter=qfilter,
            )
        except Exception as exc:
            logger.error(f"[RAGRetriever] Retrieve failed on '{collection}': {exc}")
            return []

        chunks = []
        for hit in results.points:
            p = hit.payload or {}
            chunks.append(KnowledgeChunk(
                chunk_id   = str(hit.id),
                text       = p.get("text", ""),
                score      = round(hit.score, 4),
                source     = p.get("source", ""),
                trust_tier = p.get("trust_tier", 2),
                confidence = p.get("confidence", "medium"),
                topic      = p.get("topic", ""),
                chunk_type = p.get("type", "fact"),
                metadata   = {k: v for k, v in p.items()
                              if k not in ("text", "source", "trust_tier",
                                           "confidence", "topic", "type")},
            ))

        return chunks

    def retrieve_multi(
        self,
        query:       str,
        collections: List[str],
        limit:       int = 5,
        threshold:   float = 0.60,
    ) -> List[KnowledgeChunk]:
        """
        Search across multiple collections and return merged results
        sorted by score.
        """
        all_chunks: List[KnowledgeChunk] = []
        per_col = max(2, limit)

        for col in collections:
            all_chunks.extend(
                self.retrieve(query, collection=col, limit=per_col,
                              threshold=threshold)
            )

        all_chunks.sort(key=lambda c: c.score, reverse=True)
        return all_chunks[:limit]

    # ── Context building ──────────────────────────────────────────────────────

    def build_context(
        self,
        query:       str,
        collection:  str = "teacher_knowledge",
        limit:       int = 5,
        threshold:   float = 0.60,
        max_chars:   int = 4000,
        filters:     Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Retrieve chunks and format them as an LLM-ready context block.

        Returns a string like:

            [KNOWLEDGE CONTEXT]
            Source: https://docs.python.org/3/  (trust: high)
            Python uses indentation to define code blocks...

            Source: https://realpython.com/...  (trust: medium)
            In Python, a colon followed by an indented block...

            [END CONTEXT]

        Returns an empty string if nothing relevant is found.
        """
        chunks = self.retrieve(
            query=query, collection=collection,
            limit=limit, threshold=threshold, filters=filters,
        )

        if not chunks:
            return ""

        lines  = ["[KNOWLEDGE CONTEXT]"]
        total  = 0
        used   = 0

        for chunk in chunks:
            tier_label = {1: "high", 2: "medium", 3: "low"}.get(chunk.trust_tier, "unknown")
            header     = f"Source: {chunk.source or 'internal'}  (trust: {tier_label}, score: {chunk.score})"
            body       = chunk.text.strip()

            entry_len  = len(header) + len(body) + 4
            if total + entry_len > max_chars and used > 0:
                break

            lines.append(header)
            lines.append(body)
            lines.append("")
            total += entry_len
            used  += 1

        lines.append("[END CONTEXT]")

        return "\n".join(lines)

    # ── Deletion ──────────────────────────────────────────────────────────────

    def delete_chunk(self, chunk_id: str, collection: str) -> bool:
        """Delete a specific chunk by ID. Returns True if deleted."""
        try:
            from qdrant_client.models import PointIdsList
            self._get_client().delete(
                collection_name=collection,
                points_selector=PointIdsList(points=[chunk_id]),
            )
            return True
        except Exception as exc:
            logger.warning(f"[RAGRetriever] Delete failed for {chunk_id}: {exc}")
            return False

    def clear_collection(self, collection: str) -> int:
        """Delete all chunks in a collection. Returns count deleted."""
        try:
            count = self.collection_size(collection)
            self._get_client().delete_collection(collection)
            self._collections.discard(collection)
            logger.warning(f"[RAGRetriever] Cleared collection '{collection}' ({count} chunks)")
            return count
        except Exception as exc:
            logger.error(f"[RAGRetriever] Clear failed for '{collection}': {exc}")
            return 0

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """Synchronous health snapshot for module health() methods."""
        try:
            collections = self.list_collections()
            sizes = {c: self.collection_size(c) for c in collections}
            return {
                "status":      "ok",
                "qdrant_url":  self._url,
                "collections": sizes,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


# ── Device selection ──────────────────────────────────────────────────────────

def _pick_device() -> str:
    """Select best available device: MPS > CUDA > CPU."""
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


# ── Singleton ─────────────────────────────────────────────────────────────────

_retriever: Optional[RAGRetriever] = None


def get_retriever(qdrant_url: str = "http://localhost:6333") -> RAGRetriever:
    """Get (or create) the global RAGRetriever singleton."""
    global _retriever
    if _retriever is None:
        _retriever = RAGRetriever(qdrant_url=qdrant_url)
    return _retriever
