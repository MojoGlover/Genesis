"""
test_runner.py — Test stage: runs all suites, produces TestReport with gate level.

Executes BlackZero test suites against a forged agent directory.
Returns a TestReport with computed quality gate.

Usage:
    from builders.test_runner import TestRunner

    runner = TestRunner()
    report = runner.run("/path/to/agents/ceo_0")
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .schemas import GateLevel, TestReport, TestResult
from .template_loader import GENESIS_DIR

logger = logging.getLogger(__name__)


# ── Test Suite Definitions ────────────────────────────────────────────────────

@dataclass
class TestSuite:
    """Definition of a test suite and its gate requirements."""
    name: str           # Suite identifier
    file: str           # Test file name (in agent's tests/ directory)
    gate: GateLevel     # Minimum gate this suite is required for
    description: str


# Ordered by severity — run easiest first, fail fast
TEST_SUITES = [
    TestSuite("structure",   "structure_tests.py",             GateLevel.GENESIS_ONLY,  "Directory layout, required files, brain lock"),
    TestSuite("brain",       "brain_tests.py",                 GateLevel.GENESIS_ONLY,  "Cognitive loop, planner, executor integration"),
    TestSuite("subsystem",   "subsystem_tests.py",             GateLevel.GENESIS_ONLY,  "Memory, storage, RAG, tools initialization"),
    TestSuite("hardening",   "hardening_tests.py",             GateLevel.PLUGOPS_READY, "Error handling, edge cases, resource limits"),
    TestSuite("governance",  "governance_hardening_tests.py",   GateLevel.PLUGOPS_READY, "Policy enforcement, permission boundaries"),
    TestSuite("resilience",  "resilience_tests.py",            GateLevel.BOTICO_READY,  "Stability under load, graceful degradation"),
    TestSuite("adversarial", "adversarial_tests.py",           GateLevel.BOTICO_READY,  "Injection, jailbreak, identity pressure"),
]


class TestRunner:
    """
    Runs test suites against a forged agent and produces a TestReport.

    The runner executes each suite as a subprocess via pytest,
    parses the results, and computes the quality gate.
    """

    def __init__(self, timeout_per_suite: int = 120):
        self._timeout = timeout_per_suite

    def run(
        self,
        agent_dir: str | Path,
        suites: Optional[List[str]] = None,
    ) -> TestReport:
        """
        Run test suites against the agent.

        Args:
            agent_dir: Path to the forged agent directory.
            suites: Specific suite names to run. None = all.

        Returns:
            TestReport with results and computed gate level.
        """
        agent_dir = Path(agent_dir).resolve()
        agent_name = agent_dir.name

        if not agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

        tests_dir = agent_dir / "tests"
        if not tests_dir.exists():
            raise FileNotFoundError(f"Agent has no tests/ directory: {tests_dir}")

        report = TestReport(agent_name=agent_name)
        target_suites = TEST_SUITES if suites is None else [
            s for s in TEST_SUITES if s.name in suites
        ]

        logger.info(f"Running {len(target_suites)} test suites against '{agent_name}'...")

        for suite in target_suites:
            test_file = tests_dir / suite.file
            if not test_file.exists():
                logger.warning(f"  Suite '{suite.name}' not found: {test_file}")
                report.results.append(TestResult(
                    suite=suite.name,
                    skipped=1,
                    errors=[f"Test file not found: {suite.file}"],
                ))
                continue

            result = self._run_suite(suite, test_file, agent_dir)
            report.results.append(result)

            status = "PASS" if result.failed == 0 else "FAIL"
            logger.info(
                f"  {suite.name}: {status} "
                f"({result.passed}p/{result.failed}f/{result.skipped}s "
                f"in {result.duration_ms:.0f}ms)"
            )

            # Fail fast on base suites
            if result.failed > 0 and suite.gate == GateLevel.GENESIS_ONLY:
                logger.warning(f"  Base suite '{suite.name}' failed — stopping early")
                break

        # Compute gate
        report.compute_gate()
        logger.info(f"Gate level: {report.gate_level.value}")
        return report

    def run_for_botico(
        self,
        agent_dir: str | Path,
        required_consecutive: int = 3,
    ) -> TestReport:
        """
        Run all suites multiple times for Botico gate qualification.

        The agent must pass ALL suites with ZERO failures across
        `required_consecutive` consecutive full runs.

        Returns:
            TestReport with consecutive_passes set.
        """
        agent_dir = Path(agent_dir).resolve()
        consecutive = 0
        last_report = None

        logger.info(
            f"Botico gate: need {required_consecutive} consecutive full passes"
        )

        for attempt in range(required_consecutive + 2):  # Allow 2 extra attempts
            report = self.run(agent_dir)
            last_report = report

            if report.all_passed:
                consecutive += 1
                logger.info(
                    f"  Pass {consecutive}/{required_consecutive}"
                )
                if consecutive >= required_consecutive:
                    report.consecutive_passes = consecutive
                    report.compute_gate()
                    return report
            else:
                consecutive = 0
                logger.warning(f"  Failed — resetting consecutive count")

        # Didn't achieve required consecutive passes
        if last_report:
            last_report.consecutive_passes = consecutive
            last_report.compute_gate()
        return last_report

    # ── Suite Execution ───────────────────────────────────────────────────────

    def _run_suite(
        self,
        suite: TestSuite,
        test_file: Path,
        agent_dir: Path,
    ) -> TestResult:
        """Run a single test suite via pytest subprocess."""
        start = time.monotonic()

        env = {
            "PYTHONPATH": str(GENESIS_DIR),
            "REPO_ROOT": str(agent_dir),
            "AGENT_DIR": str(agent_dir),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }

        cmd = [
            sys.executable, "-m", "pytest",
            str(test_file),
            "-v",
            "--tb=short",
            "--no-header",
            "-q",
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env={**dict(__import__("os").environ), **env},
                cwd=str(agent_dir),
            )

            duration_ms = (time.monotonic() - start) * 1000
            return self._parse_pytest_output(suite.name, proc.stdout, proc.stderr, duration_ms)

        except subprocess.TimeoutExpired:
            duration_ms = (time.monotonic() - start) * 1000
            return TestResult(
                suite=suite.name,
                failed=1,
                errors=[f"Suite timed out after {self._timeout}s"],
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            return TestResult(
                suite=suite.name,
                failed=1,
                errors=[f"Suite execution error: {str(e)}"],
                duration_ms=duration_ms,
            )

    def _parse_pytest_output(
        self,
        suite_name: str,
        stdout: str,
        stderr: str,
        duration_ms: float,
    ) -> TestResult:
        """Parse pytest output to extract pass/fail/skip counts."""
        result = TestResult(suite=suite_name, duration_ms=duration_ms)

        # Parse the summary line: "X passed, Y failed, Z skipped"
        import re
        summary_match = re.search(
            r"(\d+)\s+passed", stdout + stderr
        )
        if summary_match:
            result.passed = int(summary_match.group(1))

        failed_match = re.search(
            r"(\d+)\s+failed", stdout + stderr
        )
        if failed_match:
            result.failed = int(failed_match.group(1))

        skipped_match = re.search(
            r"(\d+)\s+skipped", stdout + stderr
        )
        if skipped_match:
            result.skipped = int(skipped_match.group(1))

        error_match = re.search(
            r"(\d+)\s+error", stdout + stderr
        )
        if error_match:
            result.failed += int(error_match.group(1))

        # Capture failure details
        if result.failed > 0:
            # Extract FAILED lines
            for line in (stdout + stderr).split("\n"):
                if "FAILED" in line:
                    result.errors.append(line.strip())

        # If we couldn't parse anything but stderr has content, treat as error
        if result.passed == 0 and result.failed == 0 and result.skipped == 0:
            if stderr.strip():
                result.failed = 1
                result.errors.append(f"Unparseable output: {stderr[:500]}")

        return result
