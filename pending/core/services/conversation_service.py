"""
Conversation Service - Session lifecycle via MemoryManager
Replaces gradio_interface.py's self.conversation_memory = [] and _add_to_memory
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class ConversationService:
    """Session-based conversation management using MemoryManager (SQLite + Qdrant)"""

    def __init__(self):
        self._memory = None
        self._session_id: Optional[str] = None
        self._conversation_id: Optional[int] = None
        self._init_memory()

    def _init_memory(self):
        """Initialize the memory backend"""
        try:
            from core.storage.memory import get_memory
            self._memory = get_memory()
            logger.info("ConversationService initialized with MemoryManager")
        except Exception as e:
            logger.warning(f"MemoryManager unavailable, using in-memory fallback: {e}")
            self._memory = None
            self._fallback_messages: List[Dict[str, str]] = []

    def start_session(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Start a new conversation session"""
        self._session_id = session_id or str(uuid.uuid4())

        if self._memory:
            try:
                self._conversation_id = self._memory.create_conversation(self._session_id)
                return {
                    "success": True,
                    "session_id": self._session_id,
                    "conversation_id": self._conversation_id,
                }
            except Exception as e:
                logger.error(f"Failed to create conversation: {e}")
                return {"success": False, "session_id": self._session_id, "error": str(e)}
        else:
            self._fallback_messages = []
            return {
                "success": True,
                "session_id": self._session_id,
                "conversation_id": 0,
            }

    def add_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a message to the current conversation"""
        # Auto-start session if needed
        if self._conversation_id is None and self._memory:
            self.start_session()

        if self._memory and self._conversation_id is not None:
            try:
                msg_id = self._memory.add_message(
                    self._conversation_id, role, content, metadata
                )
                return {"success": True, "message_id": msg_id}
            except Exception as e:
                logger.error(f"Failed to add message: {e}")
                return {"success": False, "error": str(e)}
        else:
            # In-memory fallback
            self._fallback_messages.append({"role": role, "content": content})
            # Trim to last 20 messages
            if len(self._fallback_messages) > 20:
                self._fallback_messages = self._fallback_messages[-20:]
            return {"success": True, "message_id": len(self._fallback_messages) - 1}

    def get_context(self, limit: int = 10) -> List[Dict[str, str]]:
        """Get recent conversation context as list of {role, content} dicts.

        Compatible with LLMService.generate_chat() message format.
        """
        if self._memory and self._conversation_id is not None:
            try:
                history = self._memory.get_conversation_history(
                    self._conversation_id, limit=limit
                )
                return [{"role": m["role"], "content": m["content"]} for m in history]
            except Exception as e:
                logger.error(f"Failed to get context: {e}")
                return []
        else:
            return [
                {"role": m["role"], "content": m["content"]}
                for m in self._fallback_messages[-limit:]
            ]

    def search_relevant(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Semantic search across conversation history"""
        if self._memory:
            try:
                return self._memory.semantic_search(query, limit=limit)
            except Exception as e:
                logger.error(f"Semantic search failed: {e}")
                return []
        return []

    def reset(self) -> Dict[str, Any]:
        """Reset conversation state and start fresh"""
        self._session_id = None
        self._conversation_id = None
        if not self._memory:
            self._fallback_messages = []
        return {"success": True}


# Singleton
_conversation_service = None


def get_conversation_service() -> ConversationService:
    """Get or create ConversationService singleton"""
    global _conversation_service
    if _conversation_service is None:
        _conversation_service = ConversationService()
    return _conversation_service
