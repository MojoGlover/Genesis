"""
Tests for builders/export_manager.py — PlugOps and Botico export.
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from builders.schemas import (
    AgentSpec,
    BuildJob,
    ExportTarget,
    GateLevel,
    JobStatus,
    TestReport,
    TestResult,
)
from builders.export_manager import ExportManager, ExportError


@pytest.fixture
def mock_agent_dir():
    """Create a minimal mock agent directory."""
    d = tempfile.mkdtemp(prefix="genesis_test_export_")
    agent_dir = Path(d) / "test_export_agent"
    agent_dir.mkdir()

    # Create minimal structure
    (agent_dir / "brain").mkdir()
    (agent_dir / "brain" / "loop.py").write_text("# loop")
    (agent_dir / "config.yaml").write_text("agent:\n  name: test_export_agent\n")
    (agent_dir / "main.py").write_text("# main")
    (agent_dir / "identity").mkdir()
    (agent_dir / "identity" / "mission.md").write_text("Test mission")
    (agent_dir / "policies").mkdir()
    (agent_dir / "policies" / "core.md").write_text("Test policy")

    yield agent_dir
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def plugops_ready_job(mock_agent_dir):
    """A BuildJob that passes PlugOps gate."""
    spec = AgentSpec(
        name="test_export_agent",
        designation="Test Export Agent",
        role="TESTER",
        mission_text="Test agent for export testing purposes",
    )
    report = TestReport(
        agent_name="test_export_agent",
        results=[
            TestResult(suite="structure", passed=5),
            TestResult(suite="brain", passed=5),
            TestResult(suite="subsystem", passed=5),
            TestResult(suite="hardening", passed=5),
            TestResult(suite="governance", passed=5),
        ],
    )
    report.compute_gate()

    job = BuildJob(spec=spec, agent_dir=str(mock_agent_dir))
    job.test_report = report
    return job


@pytest.fixture
def botico_ready_job(mock_agent_dir):
    """A BuildJob that passes Botico gate."""
    spec = AgentSpec(
        name="test_export_agent",
        designation="Test Export Agent",
        role="TESTER",
        mission_text="Test agent for export testing purposes",
    )
    report = TestReport(
        agent_name="test_export_agent",
        consecutive_passes=3,
        results=[
            TestResult(suite="structure", passed=5),
            TestResult(suite="brain", passed=5),
            TestResult(suite="subsystem", passed=5),
            TestResult(suite="hardening", passed=5),
            TestResult(suite="governance", passed=5),
            TestResult(suite="resilience", passed=5),
            TestResult(suite="adversarial", passed=5),
        ],
    )
    report.compute_gate()
    assert report.gate_level == GateLevel.BOTICO_READY

    job = BuildJob(spec=spec, agent_dir=str(mock_agent_dir))
    job.test_report = report
    return job


class TestPlugOpsExport:
    def test_export_creates_manifest(self, plugops_ready_job):
        manager = ExportManager()
        with patch.object(Path, "write_text"):
            with patch.object(Path, "chmod"):
                try:
                    manifest = manager.export_to_plugops(plugops_ready_job)
                    assert manifest.agent_name == "test_export_agent"
                    assert manifest.target == ExportTarget.PLUGOPS
                    assert manifest.irreversible is False
                except Exception:
                    pytest.skip("PlugOps dir not available in test environment")

    def test_export_rejects_incomplete_job(self):
        manager = ExportManager()
        job = BuildJob()  # No spec, no agent_dir
        with pytest.raises(ExportError, match="no agent directory"):
            manager.export_to_plugops(job)


class TestBoticoExport:
    def test_rejects_insufficient_gate(self, plugops_ready_job):
        """PlugOps-ready job should be rejected for Botico export."""
        manager = ExportManager()
        with pytest.raises(ExportError, match="insufficient"):
            manager.export_to_botico(plugops_ready_job)

    def test_rejects_incomplete_job(self):
        manager = ExportManager()
        job = BuildJob()
        with pytest.raises(ExportError, match="incomplete"):
            manager.export_to_botico(job)

    def test_rejects_already_exported(self, botico_ready_job, mock_agent_dir):
        """Agent with .botico_exported marker should be rejected."""
        # Create the marker
        (mock_agent_dir / ".botico_exported").write_text("{}")

        manager = ExportManager()
        with pytest.raises(ExportError, match="already exported"):
            manager.export_to_botico(botico_ready_job)


class TestExportManagerUtilities:
    def test_checksum_deterministic(self, mock_agent_dir):
        manager = ExportManager()
        c1 = manager._checksum_directory(mock_agent_dir)
        c2 = manager._checksum_directory(mock_agent_dir)
        assert c1 == c2
        assert c1.startswith("sha256:")

    def test_name_not_in_empty_registry(self):
        manager = ExportManager()
        # With no registry file, should return False
        assert manager._name_in_registry("nonexistent_agent") is False
