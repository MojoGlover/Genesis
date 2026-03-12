# memory_manager.py
# THE MEMORY MANAGER
#
# Responsibility:
#   Central interface for all memory operations — reading, writing, searching,
#   and expiring memories for this agent.
#
# What does NOT belong here:
#   - Raw database logic (that belongs in storage/)
#   - Embedding generation (that belongs in rag/)
#   - Training data or transcripts

from __future__ import annotations

from abc import ABC, abstractmethod

from BlackZero.memory.memory_schema import MemoryRecord


class MemoryManager(ABC):
    """
    Abstract base class for all memory management implementations.

    An agent derived from BlackZero subclasses MemoryManager and implements
    every abstract method. The brain's executor delegates all memory
    operations through this interface.

    Example agent implementation:
        class AgentMemoryManager(MemoryManager):
            def add_memory(self, content, metadata=None):
                record = MemoryRecord(content=content, metadata=metadata or {})
                self.store.insert("memories", record.to_dict())
                return record.id
    """

    @abstractmethod
    def add_memory(self, content: str, metadata: dict | None = None) -> str:
        """
        Store a new memory and return its unique ID.

        Args:
            content:  The text or payload to remember.
            metadata: Optional dict of key-value annotations (source, tags, ttl, etc.).

        Returns:
            The ID of the newly created MemoryRecord.
        """

    @abstractmethod
    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        """
        Retrieve a specific memory by its ID.
        Returns None if no memory with that ID exists.
        """

    @abstractmethod
    def search_memory(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        """
        Search memories by semantic similarity or keyword match.

        Args:
            query: Natural language query.
            top_k: Maximum number of results to return.

        Returns:
            Ordered list of MemoryRecords, most relevant first.
        """

    @abstractmethod
    def delete_memory(self, memory_id: str) -> bool:
        """
        Remove a memory by ID.
        Returns True if the record was found and deleted, False otherwise.
        """

    @abstractmethod
    def expire_old_memories(self) -> int:
        """
        Prune all memories that have exceeded their TTL.
        Returns the number of records removed.
        """

    def list_all(self) -> list[MemoryRecord]:
        """
        Return all stored memories. Agents may override with an efficient
        implementation. Default: not supported.
        """
        raise NotImplementedError("list_all() not implemented by this MemoryManager")
