"""
GENESIS Test Runner

Executes test suites and returns structured results.
"""

from __future__ import annotations
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class TestStatus(Enum):
    """Test execution status."""
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class TestResult:
    """Result of a single test or test suite."""
    name: str
    status: TestStatus
    duration: float
    output: str = ""
    error: Optional[str] = None
    coverage: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "duration": round(self.duration, 3),
            "output": self.output[:2000] if self.output else "",  # Truncate long output
            "error": self.error,
            "coverage": self.coverage,
            "details": self.details,
        }


@dataclass
class TestSuiteResult:
    """Aggregated results from a test suite run."""
    suite_name: str
    timestamp: datetime
    duration: float
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    coverage: Optional[float]
    results: List[TestResult]

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.errors == 0

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "timestamp": self.timestamp.isoformat(),
            "duration": round(self.duration, 3),
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "success": self.success,
            "pass_rate": round(self.pass_rate, 4),
            "coverage": self.coverage,
            "results": [r.to_dict() for r in self.results],
        }


class TestRunner:
    """
    Executes tests using various tools.

    Usage:
        runner = TestRunner(project_root="/path/to/project")

        # Run pytest
        result = runner.run_pytest("tests/")

        # Run linting
        result = runner.run_flake8()

        # Run type checking
        result = runner.run_mypy()

        # Run all checks
        results = runner.run_all()
    """

    def __init__(self, project_root: Path, timeout: int = 300):
        self.project_root = Path(project_root)
        self.timeout = timeout
        self.python = sys.executable

    def run_pytest(
        self,
        test_path: str = "tests/",
        coverage: bool = True,
        verbose: bool = True,
        markers: Optional[str] = None,
    ) -> TestSuiteResult:
        """Run pytest on specified path."""
        start = time.time()

        cmd = [self.python, "-m", "pytest", test_path]

        if verbose:
            cmd.append("-v")

        if coverage:
            cmd.extend(["--cov=.", "--cov-report=json"])

        if markers:
            cmd.extend(["-m", markers])

        cmd.append("--tb=short")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            duration = time.time() - start
            output = result.stdout + result.stderr

            # Parse results
            test_results = self._parse_pytest_output(output)
            cov_percent = self._parse_coverage()

            passed = sum(1 for r in test_results if r.status == TestStatus.PASSED)
            failed = sum(1 for r in test_results if r.status == TestStatus.FAILED)
            errors = sum(1 for r in test_results if r.status == TestStatus.ERROR)
            skipped = sum(1 for r in test_results if r.status == TestStatus.SKIPPED)

            return TestSuiteResult(
                suite_name="pytest",
                timestamp=datetime.now(),
                duration=duration,
                total=len(test_results),
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                coverage=cov_percent,
                results=test_results,
            )

        except subprocess.TimeoutExpired:
            return TestSuiteResult(
                suite_name="pytest",
                timestamp=datetime.now(),
                duration=self.timeout,
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                coverage=None,
                results=[TestResult(
                    name="pytest",
                    status=TestStatus.TIMEOUT,
                    duration=self.timeout,
                    error="Test execution timed out",
                )],
            )

        except Exception as e:
            return TestSuiteResult(
                suite_name="pytest",
                timestamp=datetime.now(),
                duration=time.time() - start,
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                coverage=None,
                results=[TestResult(
                    name="pytest",
                    status=TestStatus.ERROR,
                    duration=0,
                    error=str(e),
                )],
            )

    def run_flake8(self, paths: Optional[List[str]] = None) -> TestResult:
        """Run flake8 linting."""
        start = time.time()
        paths = paths or ["."]

        cmd = [self.python, "-m", "flake8"] + paths
        cmd.extend(["--max-line-length=120", "--exclude=venv,__pycache__,.git"])

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )

            duration = time.time() - start
            issues = result.stdout.strip().split("\n") if result.stdout.strip() else []
            issue_count = len(issues)

            return TestResult(
                name="flake8",
                status=TestStatus.PASSED if result.returncode == 0 else TestStatus.FAILED,
                duration=duration,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                details={"issue_count": issue_count, "issues": issues[:20]},
            )

        except Exception as e:
            return TestResult(
                name="flake8",
                status=TestStatus.ERROR,
                duration=time.time() - start,
                error=str(e),
            )

    def run_mypy(self, paths: Optional[List[str]] = None) -> TestResult:
        """Run mypy type checking."""
        start = time.time()
        paths = paths or ["."]

        cmd = [self.python, "-m", "mypy"] + paths
        cmd.extend(["--ignore-missing-imports", "--no-error-summary"])

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )

            duration = time.time() - start
            issues = result.stdout.strip().split("\n") if result.stdout.strip() else []
            issue_count = len([i for i in issues if ": error:" in i])

            return TestResult(
                name="mypy",
                status=TestStatus.PASSED if result.returncode == 0 else TestStatus.FAILED,
                duration=duration,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                details={"error_count": issue_count},
            )

        except Exception as e:
            return TestResult(
                name="mypy",
                status=TestStatus.ERROR,
                duration=time.time() - start,
                error=str(e),
            )

    def run_black(self, paths: Optional[List[str]] = None, check_only: bool = True) -> TestResult:
        """Run black code formatter."""
        start = time.time()
        paths = paths or ["."]

        cmd = [self.python, "-m", "black"] + paths
        if check_only:
            cmd.append("--check")
        cmd.extend(["--exclude", "venv|__pycache__|.git"])

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )

            duration = time.time() - start

            return TestResult(
                name="black",
                status=TestStatus.PASSED if result.returncode == 0 else TestStatus.FAILED,
                duration=duration,
                output=result.stdout + result.stderr,
                details={"check_only": check_only},
            )

        except Exception as e:
            return TestResult(
                name="black",
                status=TestStatus.ERROR,
                duration=time.time() - start,
                error=str(e),
            )

    def run_all(self) -> Dict[str, Any]:
        """Run all test suites and quality checks."""
        results = {}

        # Run pytest
        results["pytest"] = self.run_pytest().to_dict()

        # Run linting
        results["flake8"] = self.run_flake8().to_dict()

        # Run type checking
        results["mypy"] = self.run_mypy().to_dict()

        # Run formatting check
        results["black"] = self.run_black().to_dict()

        # Summary
        all_passed = all(
            r.get("status") == "passed" or r.get("success", False)
            for r in results.values()
        )

        return {
            "timestamp": datetime.now().isoformat(),
            "success": all_passed,
            "results": results,
        }

    def _parse_pytest_output(self, output: str) -> List[TestResult]:
        """Parse pytest output to extract individual test results."""
        results = []

        for line in output.split("\n"):
            if "::" in line and any(status in line for status in ["PASSED", "FAILED", "ERROR", "SKIPPED"]):
                parts = line.split()
                if len(parts) >= 2:
                    test_name = parts[0]
                    status_str = parts[1].upper()

                    status_map = {
                        "PASSED": TestStatus.PASSED,
                        "FAILED": TestStatus.FAILED,
                        "ERROR": TestStatus.ERROR,
                        "SKIPPED": TestStatus.SKIPPED,
                    }

                    status = status_map.get(status_str, TestStatus.ERROR)
                    results.append(TestResult(
                        name=test_name,
                        status=status,
                        duration=0,  # Would need more parsing for individual times
                    ))

        return results

    def _parse_coverage(self) -> Optional[float]:
        """Parse coverage.json if it exists."""
        cov_file = self.project_root / "coverage.json"
        if cov_file.exists():
            try:
                data = json.loads(cov_file.read_text())
                return data.get("totals", {}).get("percent_covered", None)
            except Exception:
                pass
        return None
