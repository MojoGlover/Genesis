"""
Tests for the GENESIS messaging system.
"""

import pytest
from datetime import datetime

from core.messaging import Message, MessageType, MessageBus
from core.messaging.message import HealthStatus, heartbeat, error_report


class TestMessage:
    """Tests for Message class."""

    def test_create_message(self):
        """Test creating a basic message."""
        msg = Message(
            type=MessageType.TASK_REQUEST,
            sender="test_agent",
            payload={"task": "do_something"},
        )

        assert msg.type == MessageType.TASK_REQUEST
        assert msg.sender == "test_agent"
        assert msg.payload == {"task": "do_something"}
        assert msg.recipient is None
        assert msg.id is not None

    def test_message_to_dict(self):
        """Test message serialization."""
        msg = Message(
            type=MessageType.HEARTBEAT,
            sender="agent1",
        )

        data = msg.to_dict()

        assert data["type"] == "heartbeat"
        assert data["sender"] == "agent1"
        assert "timestamp" in data
        assert "id" in data

    def test_message_reply(self):
        """Test creating a reply message."""
        original = Message(
            type=MessageType.TASK_REQUEST,
            sender="requester",
            recipient="worker",
        )

        reply = original.reply(
            type=MessageType.TASK_COMPLETE,
            payload={"result": "done"},
        )

        assert reply.sender == "worker"
        assert reply.recipient == "requester"
        assert reply.correlation_id == original.id


class TestMessageFactories:
    """Tests for message factory functions."""

    def test_heartbeat(self):
        """Test heartbeat message factory."""
        msg = heartbeat("agent1", HealthStatus.HEALTHY)

        assert msg.type == MessageType.HEARTBEAT
        assert msg.sender == "agent1"
        assert msg.payload["status"] == "healthy"

    def test_error_report(self):
        """Test error report message factory."""
        msg = error_report(
            sender="broken_agent",
            error="Something went wrong",
            context={"code": 500},
        )

        assert msg.type == MessageType.ERROR_REPORT
        assert msg.sender == "broken_agent"
        assert msg.payload["error"] == "Something went wrong"
        assert msg.payload["context"]["code"] == 500


class TestMessageBus:
    """Tests for MessageBus class."""

    def test_bus_creation(self):
        """Test creating a message bus."""
        bus = MessageBus()
        assert bus is not None

    def test_subscribe_and_publish(self):
        """Test subscribing to and publishing messages."""
        bus = MessageBus()
        bus.start()

        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe(MessageType.HEARTBEAT, handler)

        msg = Message(type=MessageType.HEARTBEAT, sender="test")
        bus.publish(msg)

        # Give worker thread time to process
        import time
        time.sleep(0.2)

        bus.stop()

        assert len(received) == 1
        assert received[0].sender == "test"

    def test_agent_subscription(self):
        """Test agent-specific subscriptions."""
        bus = MessageBus()
        bus.start()

        received = []

        def handler(msg):
            received.append(msg)

        bus.subscribe_agent("my_agent", handler)

        # Message to our agent
        msg1 = Message(
            type=MessageType.TASK_REQUEST,
            sender="other",
            recipient="my_agent",
        )
        bus.publish(msg1)

        # Message to different agent (should not receive)
        msg2 = Message(
            type=MessageType.TASK_REQUEST,
            sender="other",
            recipient="other_agent",
        )
        bus.publish(msg2)

        import time
        time.sleep(0.2)

        bus.stop()

        assert len(received) == 1
        assert received[0].recipient == "my_agent"

    def test_get_stats(self):
        """Test getting bus statistics."""
        bus = MessageBus()
        bus.start()

        stats = bus.get_stats()

        assert "messages_sent" in stats
        assert "messages_delivered" in stats
        assert "queue_size" in stats

        bus.stop()
