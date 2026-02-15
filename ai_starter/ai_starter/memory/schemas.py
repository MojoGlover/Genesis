"""Memory system schemas."""

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    """Categories for stored memories."""
    task_result = "task_result"
    learning = "learning"
    observation = "observation"
    error = "error"


class MemoryItem(BaseModel):
    """A single memory entry."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    category: MemoryCategory
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
