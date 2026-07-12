"""
rag.py — Semantic memory via ChromaDB.

Stores every completed human/assistant exchange as an embedded document.
On recall, queries the vector store for exchanges semantically relevant to the
current message — not just the most recent ones.

Integrated into the recall and respond nodes:
  recall:  search(message) → semantic_context injected alongside recency context
  respond: index(session_id, human, assistant) → persisted for future retrieval

Persistent across restarts: ChromaDB writes to data_dir/chromadb/.
Gracefully disabled if ChromaDB is unavailable — recall falls back to recency-only.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_RECENCY_PREFIX = "recent:"  # tag to skip de-dup against RAG results


class RAGClient:
    def __init__(self, data_dir: Path, agent_id: str, enabled: bool = True) -> None:
        self.agent_id  = agent_id
        self.enabled   = enabled
        self._client   = None
        self._col      = None

        if not enabled:
            return

        try:
            import chromadb
            chroma_path = data_dir / "chromadb"
            chroma_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(chroma_path))
            # Collection per agent — clean namespace
            self._col = self._client.get_or_create_collection(
                name=f"memory_{agent_id}",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"[rag] ChromaDB ready at {chroma_path} ({self._col.count()} docs)")
        except Exception as e:
            logger.warning(f"[rag] ChromaDB init failed — semantic recall disabled: {e}")
            self._client = None
            self._col    = None

    def set_fallback_dir(self, path: Path) -> None:
        """No-op — data_dir is set at init. Kept for interface consistency."""

    def index(self, session_id: str, human: str, assistant: str) -> None:
        """Store a completed exchange. Called from respond node."""
        if not self._col:
            return
        try:
            doc  = f"Q: {human}\nA: {assistant}"
            meta = {"session_id": session_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
            uid  = str(uuid.uuid4())
            self._col.add(documents=[doc], metadatas=[meta], ids=[uid])
        except Exception as e:
            logger.debug(f"[rag] index failed (non-fatal): {e}")

    def search(self, query: str, k: int = 3, exclude_ids: set[str] | None = None) -> list[str]:
        """
        Return up to k semantically relevant past exchanges.
        Results are formatted as 'human: ...' / 'assistant: ...' pairs.
        """
        if not self._col:
            return []
        try:
            n_docs = self._col.count()
            if n_docs == 0:
                return []
            n_results = min(k, n_docs)
            results = self._col.query(
                query_texts=[query],
                n_results=n_results,
                include=["documents", "distances"],
            )
            docs      = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]

            out = []
            for doc, dist in zip(docs, distances):
                # Skip if cosine distance too high (not relevant)
                if dist > 0.7:
                    continue
                # doc format: "Q: ...\nA: ..."
                lines = doc.split("\n", 1)
                human_line     = lines[0][3:] if lines[0].startswith("Q: ") else lines[0]
                assistant_line = lines[1][3:] if len(lines) > 1 and lines[1].startswith("A: ") else ""
                if exclude_ids and human_line in exclude_ids:
                    continue
                out.append(f"human: {human_line}")
                if assistant_line:
                    out.append(f"assistant: {assistant_line}")
            return out
        except Exception as e:
            logger.debug(f"[rag] search failed (non-fatal): {e}")
            return []
