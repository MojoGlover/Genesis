# vector_store.py
# VECTOR STORAGE ADAPTER
#
# Responsibility:
#   Handles vector/embedding storage and similarity search.
#
# Expected contents:
#   - Connection to vector database (e.g. Chroma, Qdrant, FAISS, or in-memory)
#   - upsert(id, embedding, metadata) — store or update a vector
#   - search(query_embedding, top_k) — retrieve nearest neighbors
#   - delete(id) — remove a vector entry
#   - Abstraction layer so the backend can be swapped without changing callers
#
# What does NOT belong here:
#   - Embedding generation logic (that belongs in rag/)
#   - SQLite persistence (that belongs in sqlite_store.py)
#   - Memory business logic (that belongs in memory/)
