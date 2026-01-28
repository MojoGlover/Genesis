"""
Qdrant Vector Store
Semantic search for conversations
"""
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any
import uuid


def _get_device() -> str:
    """Pick the best available device: MPS (M1/M2 GPU) > CUDA > CPU"""
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class QdrantStore:
    def __init__(self, url: str = "http://localhost:6333"):
        self.client = QdrantClient(url=url)
        self.embedder = SentenceTransformer('all-mpnet-base-v2', device=_get_device())
        self.collection = "genesis_memories"
        self._init_collection()
    
    def _init_collection(self):
        """Initialize collection if it doesn't exist"""
        try:
            self.client.get_collection(self.collection)
        except:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE)
            )
    
    def add_memory(
        self,
        text: str,
        metadata: Dict[str, Any]
    ) -> str:
        """Add text to vector store"""
        embedding = self.embedder.encode(text).tolist()
        point_id = str(uuid.uuid4())
        
        self.client.upsert(
            collection_name=self.collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={"text": text, **metadata}
                )
            ]
        )
        
        return point_id
    
    def search(
        self,
        query: str,
        limit: int = 5,
        score_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Semantic search for similar memories"""
        query_embedding = self.embedder.encode(query).tolist()
        
        results = self.client.query_points(
            collection_name=self.collection,
            query=query_embedding,
            limit=limit,
            score_threshold=score_threshold
        )
        
        return [
            {
                "text": hit.payload["text"],
                "score": hit.score,
                **{k: v for k, v in hit.payload.items() if k != "text"}
            }
            for hit in results.points
        ]


_qdrant = None

def get_qdrant() -> QdrantStore:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantStore()
    return _qdrant
