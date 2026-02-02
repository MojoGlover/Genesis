"""
GENESIS Message Bus - Central pub/sub broker using Python Queue.

Features:
- Async/non-blocking message delivery
- Topic-based subscriptions (by MessageType)
- Agent-specific subscriptions (by recipient name)
- All messages logged for debugging
- Thread-safe for multi-agent use
"""

from __future__ import annotations
import logging
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Callable, Dict, List, Optional, Set
import json

from .message import Message, MessageType, HealthStatus

logger = logging.getLogger(__name__)

# Type alias for message handlers
MessageHandler = Callable[[Message], None]


class MessageBus:
    """
    Central message bus for agent communication.

    Usage:
        bus = MessageBus()

        # Subscribe to message types
        bus.subscribe(MessageType.TASK_REQUEST, my_handler)

        # Subscribe to messages for a specific agent
        bus.subscribe_agent("route_optimizer", my_handler)

        # Publish a message
        bus.publish(Message(
            type=MessageType.TASK_REQUEST,
            sender="orchestrator",
            recipient="route_optimizer",
            payload={"task": {...}}
        ))
    """

    def __init__(self, log_dir: Optional[Path] = None):
        """
        Initialize the message bus.

        Args:
            log_dir: Directory to store message logs. Defaults to ~/.genesis/logs/
        """
        self._queue: Queue[Message] = Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Subscriptions
        self._type_handlers: Dict[MessageType, List[MessageHandler]] = defaultdict(list)
        self._agent_handlers: Dict[str, List[MessageHandler]] = defaultdict(list)
        self._broadcast_handlers: List[MessageHandler] = []

        # Logging
        self._log_dir = log_dir or Path.home() / ".genesis" / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._message_log: List[Dict] = []
        self._max_log_size = 1000  # Keep last 1000 messages in memory

        # Stats
        self._stats = {
            "messages_sent": 0,
            "messages_delivered": 0,
            "messages_failed": 0,
            "start_time": None,
        }

        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the message bus worker thread."""
        if self._running:
            return

        self._running = True
        self._stats["start_time"] = datetime.now()
        self._worker_thread = threading.Thread(target=self._process_messages, daemon=True)
        self._worker_thread.start()
        logger.info("Message bus started")

    def stop(self) -> None:
        """Stop the message bus."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
        self._save_log()
        logger.info("Message bus stopped")

    def publish(self, message: Message) -> None:
        """
        Publish a message to the bus.

        Args:
            message: The message to publish
        """
        self._queue.put(message)
        self._stats["messages_sent"] += 1
        self._log_message(message, "published")
        logger.debug(f"Published: {message}")

    def subscribe(self, message_type: MessageType, handler: MessageHandler) -> None:
        """
        Subscribe to a specific message type.

        Args:
            message_type: The type of message to listen for
            handler: Function to call when message is received
        """
        with self._lock:
            self._type_handlers[message_type].append(handler)
        logger.debug(f"Subscribed to {message_type.value}")

    def unsubscribe(self, message_type: MessageType, handler: MessageHandler) -> None:
        """Unsubscribe from a message type."""
        with self._lock:
            if handler in self._type_handlers[message_type]:
                self._type_handlers[message_type].remove(handler)

    def subscribe_agent(self, agent_name: str, handler: MessageHandler) -> None:
        """
        Subscribe to messages addressed to a specific agent.

        Args:
            agent_name: The agent name to listen for
            handler: Function to call when message is received
        """
        with self._lock:
            self._agent_handlers[agent_name].append(handler)
        logger.debug(f"Agent '{agent_name}' subscribed to personal messages")

    def subscribe_broadcast(self, handler: MessageHandler) -> None:
        """
        Subscribe to broadcast messages (no specific recipient).

        Args:
            handler: Function to call for broadcast messages
        """
        with self._lock:
            self._broadcast_handlers.append(handler)

    def _process_messages(self) -> None:
        """Worker thread that processes messages from the queue."""
        while self._running:
            try:
                message = self._queue.get(timeout=0.1)
                self._deliver_message(message)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                self._stats["messages_failed"] += 1

    def _deliver_message(self, message: Message) -> None:
        """Deliver a message to all relevant subscribers."""
        delivered = False

        with self._lock:
            # Deliver to type subscribers
            for handler in self._type_handlers.get(message.type, []):
                try:
                    handler(message)
                    delivered = True
                except Exception as e:
                    logger.error(f"Handler error for {message.type}: {e}")

            # Deliver to agent-specific subscribers
            if message.recipient:
                for handler in self._agent_handlers.get(message.recipient, []):
                    try:
                        handler(message)
                        delivered = True
                    except Exception as e:
                        logger.error(f"Agent handler error for {message.recipient}: {e}")
            else:
                # Broadcast to all broadcast handlers
                for handler in self._broadcast_handlers:
                    try:
                        handler(message)
                        delivered = True
                    except Exception as e:
                        logger.error(f"Broadcast handler error: {e}")

        if delivered:
            self._stats["messages_delivered"] += 1
            self._log_message(message, "delivered")
        else:
            logger.warning(f"No handlers for message: {message}")

    def _log_message(self, message: Message, action: str) -> None:
        """Log a message for debugging."""
        entry = {
            **message.to_dict(),
            "action": action,
            "logged_at": datetime.now().isoformat(),
        }
        self._message_log.append(entry)

        # Trim log if too large
        if len(self._message_log) > self._max_log_size:
            self._message_log = self._message_log[-self._max_log_size:]

    def _save_log(self) -> None:
        """Save message log to file."""
        if not self._message_log:
            return

        log_file = self._log_dir / f"messages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(log_file, "w") as f:
                json.dump(self._message_log, f, indent=2, default=str)
            logger.info(f"Message log saved to {log_file}")
        except Exception as e:
            logger.error(f"Failed to save message log: {e}")

    def get_stats(self) -> Dict:
        """Get message bus statistics."""
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "type_subscriptions": {t.value: len(h) for t, h in self._type_handlers.items()},
            "agent_subscriptions": list(self._agent_handlers.keys()),
            "uptime_seconds": (datetime.now() - self._stats["start_time"]).total_seconds()
            if self._stats["start_time"]
            else 0,
        }

    def get_recent_messages(self, limit: int = 50) -> List[Dict]:
        """Get recent messages from the log."""
        return self._message_log[-limit:]

    def clear_log(self) -> None:
        """Clear the in-memory message log."""
        self._message_log.clear()


# Singleton instance
_bus_instance: Optional[MessageBus] = None
_bus_lock = threading.Lock()


def get_message_bus() -> MessageBus:
    """Get the singleton message bus instance."""
    global _bus_instance
    with _bus_lock:
        if _bus_instance is None:
            _bus_instance = MessageBus()
            _bus_instance.start()
        return _bus_instance


def reset_message_bus() -> None:
    """Reset the singleton (mainly for testing)."""
    global _bus_instance
    with _bus_lock:
        if _bus_instance:
            _bus_instance.stop()
            _bus_instance = None
