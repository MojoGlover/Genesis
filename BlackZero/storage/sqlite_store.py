# sqlite_store.py
# SQLITE STORAGE ADAPTER
#
# Responsibility:
#   Handles all SQLite-based persistence for this agent.
#
# Expected contents:
#   - Database connection setup and teardown
#   - Table creation / schema migrations
#   - CRUD operations: insert, select, update, delete
#   - Query helpers used by memory_manager.py and executor.py
#
# What does NOT belong here:
#   - Vector/embedding storage (that belongs in vector_store.py)
#   - Memory business logic (that belongs in memory/)
#   - Loose .db files — database files must be gitignored or placed in a controlled subfolder
