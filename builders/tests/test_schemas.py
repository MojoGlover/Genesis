"""
Tests for builders/schemas.py — data structures and gate computation.
"""

import pytest
from builders.schemas import (
    AgentSpec,
    AutonomyLevel,
    BuildJob,
    ExportManifest,
    ExportTarget,
    GateLevel,
    JobStatus,
    TestReport,
    TestResult,
)


# ── AgentSpec ────────────────────────────────────────────────────────────────


class TestAgentSpec:
    def test_minimal_spec(self):
        spec = AgentSpec(
            name="test_agent",
            designation="Test Agent",
            role="TESTER",
            mission_text="A test mission for verifying builder pipeline",
        )
        assert spec.name == "test_agent"
        assert spec.model_base == "llama3.2:3b"
        assert spec.autonomy_level == AutonomyLevel.SEMI_AUTONOMOUS
        assert spec.self_realized is False
        assert spec.spec_version == "1.0.0"

    def test_spec_defaults(self):
        spec = AgentSpec(
            name="a", designation="A", role="R",
            mission_text="Mission text here for testing",
        )
        assert spec.personality["tone"] == "professional"
        assert spec.model_params["temperature"] == 0.7
        assert spec.loop_settings["check_interval_seconds"] == 5
        assert spec.routing["default"] == "llama3.2:3b"

    def test_spec_custom_values(self):
        spec = AgentSpec(
            name="custom_0",
            designation="Custom Zero",
            role="CUSTOM",
            mission_text="Custom mission text for testing",
            autonomy_level=AutonomyLevel.FULLY_AUTONOMOUS,
            self_realized=True,
            model_base="codellama:7b",
        )
        assert spec.autonomy_level == AutonomyLevel.FULLY_AUTONOMOUS
        assert spec.self_realized is True
        assert spec.model_base == "codellama:7b"


# ── TestReport Gate Computation ──────────────────────────────────────────────


class TestGateComputation:
    def _make_result(self, suite, passed=5, failed=0, skipped=0):
        return TestResult(suite=suite, passed=passed, failed=failed, skipped=skipped)

    def test_genesis_only_when_base_fails(self):
        report = TestReport(
            agent_name="test",
            results=[
                self._make_result("structure", failed=1),
                self._make_result("brain"),
                self._make_result("subsystem"),
            ],
        )
        gate = report.compute_gate()
        assert gate == GateLevel.GENESIS_ONLY
        assert report.all_passed is False

    def test_genesis_only_when_brain_missing(self):
        report = TestReport(
            agent_name="test",
            results=[
                self._make_result("structure"),
                self._make_result("subsystem"),
            ],
        )
        gate = report.compute_gate()
        assert gate == GateLevel.GENESIS_ONLY

    def test_plugops_ready(self):
        report = TestReport(
            agent_name="test",
            results=[
                self._make_result("structure"),
                self._make_result("brain"),
                self._make_result("subsystem"),
                self._make_result("hardening"),
                self._make_result("governance"),
            ],
        )
        gate = report.compute_gate()
        assert gate == GateLevel.PLUGOPS_READY

    def test_plugops_not_ready_without_governance(self):
        report = TestReport(
            agent_name="test",
            results=[
                self._make_result("structure"),
                self._make_result("brain"),
                self._make_result("subsystem"),
                self._make_result("hardening"),
            ],
        )
        gate = report.compute_gate()
        assert gate == GateLevel.GENESIS_ONLY

    def test_botico_ready_requires_all_and_consecutive(self):
        report = TestReport(
            agent_name="test",
            consecutive_passes=3,
            results=[
                self._make_result("structure"),
                self._make_result("brain"),
                self._make_result("subsystem"),
                self._make_result("hardening"),
                self._make_result("governance"),
                self._make_result("resilience"),
                self._make_result("adversarial"),
            ],
        )
        gate = report.compute_gate()
        assert gate == GateLevel.BOTICO_READY
        assert report.all_passed is True

    def test_botico_not_ready_without_consecutive(self):
        report = TestReport(
            agent_name="test",
            consecutive_passes=2,  # Need 3
            results=[
                self._make_result("structure"),
                self._make_result("brain"),
                self._make_result("subsystem"),
                self._make_result("hardening"),
                self._make_result("governance"),
                self._make_result("resilience"),
                self._make_result("adversarial"),
            ],
        )
        gate = report.compute_gate()
        assert gate == GateLevel.PLUGOPS_READY  # Falls back

    def test_botico_not_ready_with_any_failure(self):
        report = TestReport(
            agent_name="test",
            consecutive_passes=3,
            results=[
                self._make_result("structure"),
                self._make_result("brain"),
                self._make_result("subsystem"),
                self._make_result("hardening"),
                self._make_result("governance"),
                self._make_result("resilience", failed=1),
                self._make_result("adversarial"),
            ],
        )
        gate = report.compute_gate()
        assert gate != GateLevel.BOTICO_READY


# ── BuildJob ─────────────────────────────────────────────────────────────────


class TestBuildJob:
    def test_job_creation(self):
        job = BuildJob()
        assert job.status == JobStatus.PENDING
        assert job.job_id is not None
        assert len(job.log) == 0
        assert len(job.errors) == 0

    def test_job_logging(self):
        job = BuildJob()
        job.log_event("test event")
        assert len(job.log) == 1
        assert "test event" in job.log[0]

    def test_job_fail(self):
        job = BuildJob()
        job.fail("something broke")
        assert job.status == JobStatus.FAILED
        assert "something broke" in job.errors
        assert job.completed_at is not None

    def test_job_complete(self):
        job = BuildJob()
        job.complete()
        assert job.status == JobStatus.COMPLETE
        assert job.completed_at is not None
