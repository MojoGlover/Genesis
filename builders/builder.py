"""
builder.py — Main Builder orchestrator. The core of GENESIS.

Pipeline state machine:
    propose → forge → test → export (PlugOps) or realize → export (Botico)

Usage:
    from builders.builder import Builder

    builder = Builder()

    # Full pipeline
    job = builder.propose_and_forge("CEO")
    job = builder.test(job)
    job = builder.export_plugops(job)

    # Or step by step
    spec = builder.propose("RESEARCHER")
    job = builder.forge(spec)
    job = builder.test(job)
    job = builder.realize(job)
    job = builder.export_botico(job)     # point of no return
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schemas import (
    AgentSpec,
    BuildJob,
    ExportManifest,
    ExportTarget,
    GateLevel,
    JobStatus,
    TestReport,
)
from .spec_generator import SpecGenerator
from .forger import Forger, ForgeError
from .test_runner import TestRunner
from .template_loader import GENESIS_DIR

logger = logging.getLogger(__name__)


class BuildError(Exception):
    """Raised when a build pipeline step fails."""
    pass


class Builder:
    """
    The GENESIS Builder — the agent factory core.

    Orchestrates the full agent lifecycle from proposal to export.
    Maintains a job registry for tracking builds.
    """

    def __init__(self):
        self._generator = SpecGenerator()
        self._forger = Forger()
        self._runner = TestRunner()
        self._jobs: Dict[str, BuildJob] = {}
        self._jobs_dir = GENESIS_DIR / "builders" / ".jobs"
        self._jobs_dir.mkdir(exist_ok=True)

    # ── Propose ───────────────────────────────────────────────────────────────

    def propose(
        self,
        role: str,
        mission_file: Optional[str] = None,
        name: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> AgentSpec:
        """Generate an AgentSpec for the given role."""
        return self._generator.propose(role, mission_file, name, overrides)

    # ── Forge ─────────────────────────────────────────────────────────────────

    def forge(self, spec: AgentSpec, overwrite: bool = False) -> BuildJob:
        """Forge a new agent from spec. Returns a BuildJob."""
        job = BuildJob(spec=spec, status=JobStatus.FORGING)
        job.log_event(f"Forging {spec.designation} ({spec.name})...")

        try:
            agent_dir = self._forger.forge(spec, overwrite=overwrite)
            job.agent_dir = str(agent_dir)
            job.status = JobStatus.PENDING  # Ready for testing
            job.log_event(f"Forged at {agent_dir}")
        except ForgeError as e:
            job.fail(str(e))

        self._save_job(job)
        return job

    def propose_and_forge(
        self,
        role: str,
        mission_file: Optional[str] = None,
        name: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> BuildJob:
        """Convenience: propose + forge in one call."""
        spec = self.propose(role, mission_file, name, overrides)
        return self.forge(spec, overwrite=overwrite)

    # ── Test ──────────────────────────────────────────────────────────────────

    def test(
        self,
        job: BuildJob,
        suites: Optional[List[str]] = None,
    ) -> BuildJob:
        """Run test suites against a forged agent."""
        if not job.agent_dir:
            job.fail("No agent directory — forge first")
            return job

        job.status = JobStatus.TESTING
        job.log_event("Running test suites...")

        try:
            report = self._runner.run(job.agent_dir, suites=suites)
            job.test_report = report
            job.log_event(
                f"Tests complete: gate={report.gate_level.value}, "
                f"all_passed={report.all_passed}"
            )

            # Log individual suite results
            for r in report.results:
                status = "PASS" if r.failed == 0 else "FAIL"
                job.log_event(
                    f"  {r.suite}: {status} "
                    f"({r.passed}p/{r.failed}f/{r.skipped}s)"
                )

            if report.all_passed:
                job.status = JobStatus.PENDING  # Ready for export
            else:
                job.log_event("Some tests failed — agent stays in GENESIS")
                job.status = JobStatus.PENDING  # Can still re-test or fix

        except Exception as e:
            job.fail(f"Test execution error: {e}")

        self._save_job(job)
        return job

    def test_for_botico(self, job: BuildJob) -> BuildJob:
        """Run full test suite 3+ times for Botico gate."""
        if not job.agent_dir:
            job.fail("No agent directory — forge first")
            return job

        job.status = JobStatus.TESTING
        job.log_event("Running Botico gate qualification (3 consecutive passes)...")

        try:
            report = self._runner.run_for_botico(job.agent_dir)
            job.test_report = report
            job.log_event(
                f"Botico gate: {report.consecutive_passes}/3 consecutive passes, "
                f"gate={report.gate_level.value}"
            )
        except Exception as e:
            job.fail(f"Botico test error: {e}")

        self._save_job(job)
        return job

    # ── Export to PlugOps ──────────────────────────────────────────────────────

    def export_plugops(self, job: BuildJob) -> BuildJob:
        """Export agent to PlugOps. Reversible."""
        if not job.test_report:
            job.fail("Agent not tested — run tests first")
            return job

        if job.test_report.gate_level.value < GateLevel.PLUGOPS_READY.value:
            # Compare enum values
            plugops_gates = [GateLevel.PLUGOPS_READY, GateLevel.BOTICO_READY]
            if job.test_report.gate_level not in plugops_gates:
                job.fail(
                    f"Gate level '{job.test_report.gate_level.value}' insufficient. "
                    f"Need at least 'plugops_ready'."
                )
                return job

        job.status = JobStatus.EXPORTING
        job.log_event("Exporting to PlugOps...")

        try:
            # Import here to avoid circular deps
            from .export_manager import ExportManager
            manager = ExportManager()
            manifest = manager.export_to_plugops(job)
            job.export_manifest = manifest
            job.complete()
            job.log_event(f"Exported to PlugOps: {manifest.bridge_script}")
        except Exception as e:
            job.fail(f"PlugOps export error: {e}")

        self._save_job(job)
        return job

    # ── Self-Realization ──────────────────────────────────────────────────────

    def realize(self, job: BuildJob) -> BuildJob:
        """Add self-improvement loop to agent. Makes it self-realized."""
        if not job.agent_dir:
            job.fail("No agent directory — forge first")
            return job

        job.log_event("Realizing agent — adding self-improvement loop...")

        try:
            from .realizer import Realizer
            realizer = Realizer()
            realizer.realize(job.agent_dir)
            job.log_event("Agent is now self-realized")

            # Update spec
            if job.spec:
                job.spec.self_realized = True

        except Exception as e:
            job.fail(f"Realization error: {e}")

        self._save_job(job)
        return job

    # ── Export to Botico — POINT OF NO RETURN ─────────────────────────────────

    def export_botico(self, job: BuildJob) -> BuildJob:
        """
        Export agent to Botico. IRREVERSIBLE.

        Requires:
            - All test suites passed
            - 3 consecutive full passes
            - Gate level = botico_ready

        Once exported:
            - Agent name is permanently reserved
            - GENESIS copy becomes read-only
            - No recall possible
        """
        if not job.test_report:
            job.fail("Agent not tested — run test_for_botico first")
            return job

        if job.test_report.gate_level != GateLevel.BOTICO_READY:
            job.fail(
                f"Gate level '{job.test_report.gate_level.value}' insufficient. "
                f"Need 'botico_ready' (all suites pass, 3 consecutive runs)."
            )
            return job

        job.status = JobStatus.EXPORTING
        job.log_event("POINT OF NO RETURN — Exporting to Botico...")

        try:
            from .export_manager import ExportManager
            manager = ExportManager()
            manifest = manager.export_to_botico(job)
            job.export_manifest = manifest
            job.complete()
            job.log_event(
                f"Agent '{job.spec.name}' is now in Botico. "
                "This is permanent. No recall."
            )
        except Exception as e:
            job.fail(f"Botico export error: {e}")

        self._save_job(job)
        return job

    # ── Job Management ────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> Optional[BuildJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[BuildJob]:
        return list(self._jobs.values())

    def list_agents(self) -> List[str]:
        """List all forged agents in GENESIS."""
        agents_dir = GENESIS_DIR / "agents"
        if not agents_dir.exists():
            return []
        return sorted(
            d.name for d in agents_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def list_botico_exports(self) -> List[Dict[str, Any]]:
        """List all agents exported to Botico (irreversible registry)."""
        registry_path = GENESIS_DIR / "builders" / "botico_registry.jsonl"
        if not registry_path.exists():
            return []
        entries = []
        for line in registry_path.read_text().strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def _save_job(self, job: BuildJob) -> None:
        """Persist job to memory and disk."""
        self._jobs[job.job_id] = job
        job_file = self._jobs_dir / f"{job.job_id}.json"
        job_data = {
            "job_id": job.job_id,
            "status": job.status.value,
            "agent_name": job.spec.name if job.spec else None,
            "agent_dir": job.agent_dir,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "errors": job.errors,
            "log": job.log,
            "gate_level": job.test_report.gate_level.value if job.test_report else None,
        }
        job_file.write_text(json.dumps(job_data, indent=2) + "\n")
