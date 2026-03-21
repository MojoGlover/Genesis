"""
Tests for builders/realizer.py — self-realization engine.
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from builders.realizer import Realizer, RealizationError


@pytest.fixture
def mock_agent_dir():
    """Create a minimal forged agent directory for testing."""
    d = tempfile.mkdtemp(prefix="genesis_test_realize_")
    agent_dir = Path(d) / "test_realize_agent"
    agent_dir.mkdir()

    # Minimal forged structure
    (agent_dir / "brain").mkdir()
    (agent_dir / "brain" / "loop.py").write_text("# loop")
    (agent_dir / "brain" / "planner.py").write_text("# planner")
    (agent_dir / "brain" / "executor.py").write_text("# executor")
    (agent_dir / "brain" / "router.py").write_text("# router")

    config = {
        "agent": {
            "name": "test_realize_agent",
            "designation": "Test Realize Agent",
            "role": "TESTER",
            "self_realized": False,
        },
        "loop": {"check_interval_seconds": 5},
        "data_dir": str(agent_dir / "data"),
    }
    (agent_dir / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False)
    )

    (agent_dir / "tests").mkdir()
    (agent_dir / "tests" / "test_structure.py").write_text("# tests")

    # Build manifest
    (agent_dir / ".build_manifest.json").write_text(json.dumps({
        "builder_version": "1.0.0",
        "template": "BlackZero",
    }))

    yield agent_dir
    shutil.rmtree(d, ignore_errors=True)


class TestRealizerValidation:
    def test_rejects_missing_dir(self):
        realizer = Realizer()
        with pytest.raises(RealizationError, match="not found"):
            realizer.realize("/nonexistent/path/to/agent")

    def test_rejects_no_brain(self):
        d = tempfile.mkdtemp(prefix="genesis_test_nobrain_")
        agent_dir = Path(d) / "no_brain_agent"
        agent_dir.mkdir()
        (agent_dir / "config.yaml").write_text("agent: {name: test}")

        realizer = Realizer()
        try:
            with pytest.raises(RealizationError, match="brain"):
                realizer.realize(agent_dir)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_rejects_botico_exported(self, mock_agent_dir):
        (mock_agent_dir / ".botico_exported").write_text("{}")
        realizer = Realizer()
        with pytest.raises(RealizationError, match="Botico"):
            realizer.realize(mock_agent_dir)


class TestRealizationProcess:
    def test_installs_self_improvement_module(self, mock_agent_dir):
        realizer = Realizer()
        module_dir = realizer.realize(mock_agent_dir)

        assert module_dir.exists()
        assert (module_dir / "module.py").exists()
        assert (module_dir / "improvement_loop.py").exists()
        assert (module_dir / "introspector.py").exists()
        assert (module_dir / "benchmark.py").exists()
        assert (module_dir / "journal.py").exists()

    def test_updates_config(self, mock_agent_dir):
        realizer = Realizer()
        realizer.realize(mock_agent_dir, cadence_cycles=100)

        config = yaml.safe_load((mock_agent_dir / "config.yaml").read_text())
        assert config["self_improvement"]["enabled"] is True
        assert config["self_improvement"]["cadence_cycles"] == 100
        assert "agent_dir" in config

    def test_creates_data_directory(self, mock_agent_dir):
        realizer = Realizer()
        realizer.realize(mock_agent_dir)

        assert (mock_agent_dir / "data").exists()
        assert (mock_agent_dir / "data" / "benchmark_results").exists()

    def test_updates_build_manifest(self, mock_agent_dir):
        realizer = Realizer()
        realizer.realize(mock_agent_dir)

        manifest = json.loads(
            (mock_agent_dir / ".build_manifest.json").read_text()
        )
        assert manifest["self_realized"] is True
        assert "self_realized_at" in manifest
        assert manifest["self_improvement_config"]["hook"] == "input_feed"
        assert "never modifies brain/" in manifest["self_improvement_config"]["constraints"]

    def test_rejects_double_realization(self, mock_agent_dir):
        realizer = Realizer()
        realizer.realize(mock_agent_dir)

        with pytest.raises(RealizationError, match="already has"):
            realizer.realize(mock_agent_dir)


class TestUnrealize:
    def test_disables_improvement(self, mock_agent_dir):
        realizer = Realizer()
        realizer.realize(mock_agent_dir)

        assert realizer.is_realized(mock_agent_dir) is True

        realizer.unrealize(mock_agent_dir)

        config = yaml.safe_load((mock_agent_dir / "config.yaml").read_text())
        assert config["self_improvement"]["enabled"] is False
        assert realizer.is_realized(mock_agent_dir) is False


class TestIsRealized:
    def test_not_realized_by_default(self, mock_agent_dir):
        realizer = Realizer()
        assert realizer.is_realized(mock_agent_dir) is False

    def test_realized_after_realize(self, mock_agent_dir):
        realizer = Realizer()
        realizer.realize(mock_agent_dir)
        assert realizer.is_realized(mock_agent_dir) is True
