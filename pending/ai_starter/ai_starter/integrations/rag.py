"""RAG (Retrieval-Augmented Generation) system for context enrichment."""

from typing import Any

from pydantic import BaseModel, Field

from ai_starter.memory.storage import MemoryStore


class RAGConfig(BaseModel):
    """Configuration for RAG system."""
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k: int = 5
    similarity_threshold: float = 0.7


class Document(BaseModel):
    """A document for RAG indexing."""
    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None


class RAGSystem:
    """Retrieval-Augmented Generation system."""

    def __init__(self, memory: MemoryStore, config: RAGConfig):
        self.memory = memory
        self.config = config
        self.documents: dict[str, Document] = {}

    def index_document(self, doc: Document) -> None:
        """Index a document for retrieval."""
        # Chunk the document
        chunks = self._chunk_text(doc.content)
        
        # Store each chunk (in production, would generate embeddings)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc.id}_chunk_{i}"
            self.documents[chunk_id] = Document(
                id=chunk_id,
                content=chunk,
                metadata={**doc.metadata, "chunk_index": i, "parent_id": doc.id},
            )

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks."""
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = start + self.config.chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start += self.config.chunk_size - self.config.chunk_overlap
        
        return chunks

    async def retrieve(self, query: str, top_k: int | None = None) -> list[Document]:
        """Retrieve relevant documents for a query."""
        k = top_k or self.config.top_k
        
        # Use memory FTS search as retrieval mechanism
        results = self.memory.search(query, limit=k)
        
        # Convert to Documents
        docs = []
        for item in results:
            docs.append(Document(
                id=item.id,
                content=item.content,
                metadata=item.metadata,
            ))
        
        return docs

    async def augment_prompt(self, query: str, base_prompt: str) -> str:
        """Augment a prompt with retrieved context."""
        docs = await self.retrieve(query)
        
        if not docs:
            return base_prompt
        
        context = "\n\n".join(
            f"[Context {i+1}]: {doc.content}"
            for i, doc in enumerate(docs)
        )
        
        augmented = f"{base_prompt}\n\nRelevant Context:\n{context}\n\nQuery: {query}"
        return augmented

    def clear_index(self) -> None:
        """Clear all indexed documents."""
        self.documents.clear()


def create_rag_system(memory: MemoryStore, config: dict[str, Any]) -> RAGSystem:
    """Factory to create RAG system from config."""
    rag_config = RAGConfig(**config.get("rag", {}))
    return RAGSystem(memory, rag_config)
