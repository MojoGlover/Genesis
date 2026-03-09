"""
Memory Manager
Handles conversation storage and retrieval with semantic search
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from .vector.qdrant_store import get_qdrant


class MemoryManager:
    def __init__(self, db_path: str = "./data/memory.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.qdrant = get_qdrant()
        self._init_db()
    
    def _init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                vector_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def create_conversation(self, session_id: str) -> int:
        """Create new conversation"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (session_id) VALUES (?)",
            (session_id,)
        )
        conv_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return conv_id
    
    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add message to conversation and vector store"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Add to vector store for semantic search
        vector_id = self.qdrant.add_memory(
            text=content,
            metadata={
                "conversation_id": conversation_id,
                "role": role,
                **(metadata or {})
            }
        )
        
        metadata_json = json.dumps(metadata) if metadata else None
        
        cursor.execute(
            "INSERT INTO messages (conversation_id, role, content, metadata, vector_id) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, metadata_json, vector_id)
        )
        
        msg_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return msg_id
    
    def get_conversation_history(
        self,
        conversation_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent messages from conversation"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT role, content, metadata, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (conversation_id, limit))
        
        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        for msg in messages:
            if msg['metadata']:
                msg['metadata'] = json.loads(msg['metadata'])
        
        return list(reversed(messages))
    
    def semantic_search(
        self,
        query: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for semantically similar memories"""
        return self.qdrant.search(query, limit=limit)


# Singleton instance
_memory = None

def get_memory() -> MemoryManager:
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory
