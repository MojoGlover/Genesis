# memory_schema.py
# MEMORY SCHEMA DEFINITIONS
#
# Responsibility:
#   Defines the data structures used to represent memories.
#
# Expected contents:
#   - Memory dataclass or TypedDict with fields such as:
#       id        — unique identifier
#       content   — the memory text or payload
#       source    — where this memory came from (user, tool, inference)
#       timestamp — when it was created
#       ttl       — time-to-live (None = permanent)
#       tags      — optional classification labels
#       embedding — optional vector (if stored inline)
#   - Any enums or constants used across memory logic
#
# What does NOT belong here:
#   - Business logic or memory operations (that belongs in memory_manager.py)
#   - Storage mechanics (that belongs in storage/)
