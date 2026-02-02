"""
Tests for the GENESIS agent framework.
"""

import pytest
from unittest.mock import MagicMock, patch

from core.framework import AgentBase, AgentConfig, AgentState
from core.framework.agent_base import AutonomyLevel
from core.messaging.message import HealthStatus


class TestAgentConfig:
    """Tests for AgentConfig class."""

    def test_create_config(self):
        """Test creating an agent config."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test mission",
        )

        assert config.agent_name == "test_agent"
        assert config.mission == "Test mission"
        assert config.autonomy_level == AutonomyLevel.SUPERVISED

    def test_config_defaults(self):
        """Test config default values."""
        config = AgentConfig(
            agent_name="test",
            mission="test",
        )

        assert config.heartbeat_interval == 5.0
        assert config.error_threshold == 3
        assert config.alert_on_failure is True
        assert config.capabilities == {}
        assert config.tools == []

    def test_config_to_dict(self):
        """Test config serialization."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test mission",
            capabilities={"feature1": True},
            tools=["tool1", "tool2"],
        )

        data = config.to_dict()

        assert data["agent_name"] == "test_agent"
        assert data["mission"] == "Test mission"
        assert data["capabilities"]["feature1"] is True
        assert "tool1" in data["tools"]


class ConcreteAgent(AgentBase):
    """Concrete implementation for testing."""

    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.executed_tasks = []

    def execute_task(self, task):
        self.executed_tasks.append(task)
        return {"status": "completed", "task": task}


class TestAgentBase:
    """Tests for AgentBase class."""

    def test_create_agent(self):
        """Test creating an agent."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test mission",
        )

        agent = ConcreteAgent(config)

        assert agent.name == "test_agent"
        assert agent.mission == "Test mission"
        assert agent.state == AgentState.INITIALIZING

    def test_agent_start_stop(self):
        """Test agent lifecycle."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test",
        )

        agent = ConcreteAgent(config)

        # Mock message bus
        with patch('core.framework.agent_base.get_message_bus') as mock_bus:
            mock_bus.return_value = MagicMock()

            agent.start()
            assert agent.state == AgentState.READY

            agent.stop()
            assert agent.state == AgentState.STOPPED

    def test_execute_task(self):
        """Test task execution."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test",
        )

        agent = ConcreteAgent(config)

        result = agent.execute_task({"type": "test_task"})

        assert result["status"] == "completed"
        assert len(agent.executed_tasks) == 1

    def test_health_reporting(self):
        """Test health report generation."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test",
        )

        agent = ConcreteAgent(config)

        report = agent.report_health()

        assert report["agent"] == "test_agent"
        assert report["health"] == "healthy"
        assert "stats" in report

    def test_error_handling(self):
        """Test error handling updates health."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test",
            error_threshold=2,
        )

        agent = ConcreteAgent(config)

        # First error - should stay healthy
        agent.handle_error(Exception("Error 1"), {})
        assert agent.health_status == HealthStatus.HEALTHY

        # Second error - should degrade
        agent.handle_error(Exception("Error 2"), {})
        assert agent.health_status == HealthStatus.DEGRADED

    def test_reset_error_count(self):
        """Test resetting error count."""
        config = AgentConfig(
            agent_name="test_agent",
            mission="Test",
            error_threshold=1,
        )

        agent = ConcreteAgent(config)

        # Cause degradation
        agent.handle_error(Exception("Error"), {})
        assert agent.health_status == HealthStatus.DEGRADED

        # Reset
        agent.reset_error_count()
        assert agent.health_status == HealthStatus.HEALTHY


class TestAutonomyLevels:
    """Tests for autonomy level handling."""

    def test_supervised_level(self):
        """Test supervised autonomy level."""
        config = AgentConfig(
            agent_name="test",
            mission="Test",
            autonomy_level=AutonomyLevel.SUPERVISED,
        )

        agent = ConcreteAgent(config)
        assert agent.autonomy_level == AutonomyLevel.SUPERVISED

    def test_fully_autonomous_level(self):
        """Test fully autonomous level."""
        config = AgentConfig(
            agent_name="test",
            mission="Test",
            autonomy_level=AutonomyLevel.FULLY_AUTONOMOUS,
        )

        agent = ConcreteAgent(config)
        assert agent.autonomy_level == AutonomyLevel.FULLY_AUTONOMOUS
