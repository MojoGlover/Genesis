# embedding_router.py
# THE EMBEDDING ROUTER
#
# Responsibility:
#   Generates embeddings from text and routes to the correct embedding provider.
#
# Expected contents:
#   - embed(text) — main embedding interface, returns a vector
#   - Provider selection logic (e.g. OpenAI, local model, Ollama)
#   - Batched embedding support for indexing
#   - Abstraction layer so the embedding provider can be swapped without changing callers
#
# What does NOT belong here:
#   - Retrieval logic (that belongs in retriever.py)
#   - Storage of embeddings (that belongs in storage/vector_store.py)
#   - Model routing for generation (that belongs in models/)
