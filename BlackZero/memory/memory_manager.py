# memory_manager.py
# THE MEMORY MANAGER
#
# Responsibility:
#   Central interface for all memory operations — reading, writing, searching,
#   and expiring memories for this agent.
#
# Expected contents:
#   - add_memory(content, metadata) — store a new memory
#   - get_memory(id) — retrieve a specific memory by ID
#   - search_memory(query) — semantic or keyword search across memories
#   - delete_memory(id) — remove a memory by ID
#   - expire_old_memories() — prune memories past their TTL
#   - Delegates actual persistence to storage/ adapters
#
# What does NOT belong here:
#   - Raw database logic (that belongs in storage/)
#   - Embedding generation (that belongs in rag/)
#   - Training data or transcripts
