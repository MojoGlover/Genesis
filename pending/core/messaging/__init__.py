"""
GENESIS Messaging System - Python Queue-based message bus for agent communication.
"""

from .message import Message, MessageType
from .message_bus import MessageBus, get_message_bus

__all__ = [
    'Message',
    'MessageType',
    'MessageBus',
    'get_message_bus',
]
