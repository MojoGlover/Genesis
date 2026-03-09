# indexer.py
# THE INDEXER
#
# Responsibility:
#   Processes and indexes documents or data into the vector store.
#
# Expected contents:
#   - index_document(content, metadata) — chunk, embed, and store a document
#   - index_dataset(path) — batch index a dataset from datasets/
#   - Chunking strategy (fixed size, sentence-based, semantic, etc.)
#   - Calls embedding_router.py for embeddings
#   - Calls storage/vector_store.py to persist results
#
# What does NOT belong here:
#   - Retrieval logic (that belongs in retriever.py)
#   - Raw datasets (those go in datasets/)
#   - Evaluation logic (that belongs in evals/)
