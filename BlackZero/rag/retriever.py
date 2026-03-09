# retriever.py
# THE RETRIEVER
#
# Responsibility:
#   Retrieves relevant context from the vector store given a query.
#
# Expected contents:
#   - retrieve(query, top_k) — main retrieval interface
#   - Converts query to embedding via embedding_router.py
#   - Calls vector_store.py to find nearest neighbors
#   - Formats and returns retrieved chunks for use by executor.py
#   - Optional: re-ranking or filtering of results
#
# What does NOT belong here:
#   - Raw datasets or embedded documents (those go in datasets/)
#   - Storage logic (that belongs in storage/)
#   - Evaluation logic (that belongs in evals/)
