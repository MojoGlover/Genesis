"""
Tests for builders/builder.py — the main orchestrator.

Integration-level tests that verify the pipeline stages work together.
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from builders.schemas import (
    AgentSpec,
    BuildJob,
    GateLevel,
    JobStatus,
    TestReport,
    TestResult,
)
from builders.builder import Builder, BuildError


@pytest.fixture
def temp_genesis(tmp_path):
    """Create a minimal GENESIS structure for testing."""
    genesis = tmp_path / "GENESIS"
    genesis.mkdir()
    (genesis / "agents").mkdir()
    (genesis / "builders").mkdir()
    (genesis / "builders" / ".jobs").mkdir()
    return genesis


class TestBuilderPropose:
    def test_propose_returns_spec(self):
        builder = Builder()
        with patch.object(builder._generator, "propose") as mock_propose:
            mock_spec = AgentSpec(
                name="ceo_0",
                designation="CEO Zero",
                role="CEO",
                mission_text="Lead the organization with strategic vision and decisive action",
            )
            mock_propose.return_value = mock_spec

            spec = builder.propose("CEO")
            assert spec.name == "ceo_0"
            assert spec.role == "CEO"


class TestBuilderTest:
    def test_test_requires_agent_dir(self):
        builder = Builder()
        job = BuildJob()  # No agent_dir
        result = builder.test(job)
        assert result.status == JobStatus.FAILED
        assert "forge first" in result.errors[0]

    def test_test_updates_job_status(self):
        builder = Builder()
        job = BuildJob(agent_dir="/tmp/fake_agent")

        mock_report = TestReport(
            agent_name="fake",
            all_passed=True,
            results=[
                TestResult(suite="structure", passed=5),
                TestResult(suite="brain", passed=5),
                TestResult(suite="subsystem", passed=5),
            ],
        )

        with patch.object(builder._runner, "run", return_value=mock_report):
            result = builder.test(job)
            assert result.test_report is not None
            assert result.test_report.all_passed is True


class TestBuilderExportPlugOps:
    def test_export_requires_tests(self):
        builder = Builder()
        job = BuildJob(agent_dir="/tmp/fake")
        result = builder.export_plugops(job)
        assert result.status == JobStatus.FAILED
        assert "not tested" in result.errors[0]

    def test_export_checks_gate_level(self):
        builder = Builder()
        job = BuildJob(agent_dir="/tmp/fake")
        job.test_report = TestReport(
            agent_name="fake",
            gate_level=GateLevel.GENESIS_ONLY,
        )
        result = builder.export_plugops(job)
        assert result.status == JobStatus.FAILED


class TestBuilderExportBotico:
    def test_botico_requires_tests(self):
        builder = Builder()
        job = BuildJob(agent_dir="/tmp/fake")
        result = builder.export_botico(job)
        assert result.status == JobStatus.FAILED
        assert "not tested" in result.errors[0]

    def test_botico_requires_botico_ready(self):
        builder = Builder()
        job = BuildJob(agent_dir="/tmp/fake")
        job.test_report = TestReport(
            agent_name="fake",
            gate_level=GateLevel.PLUGOPS_READY,
        )
        result = builder.export_botico(job)
        assert result.status == JobStatus.FAILED
        assert "insufficient" in result.errors[0].lower()


class TestBuilderRealize:
    def test_realize_requires_agent_dir(self):
        builder = Builder()
        job = BuildJob()
        result = builder.realize(job)
        assert result.status == JobStatus.FAILED
        assert "forge first" in result.errors[0]


class TestBuilderJobManagement:
    def test_list_jobs_empty(self):
        builder = Builder()
        assert builder.list_jobs() == []

    def test_list_botico_exports_empty(self):
        builder = Builder()
        exports = builder.list_botico_exports()
        # May or may not be empty depending on existing registry
        assert isinstance(exports, list)
