"""
benchmark.py — Runs the agent's own test suite and produces comparable scores.

Used by the improvement loop to measure performance before and after
a mutation. Results are deterministic enough to detect real improvements.

Never modifies brain/, policies/, or code.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Runs agent test suites and produces scored results."""

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir
        self._tests_dir = agent_dir / "tests"
        self._results_dir = agent_dir / "data" / "benchmark_results"
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._last_result: Dict[str, Any] = {}

    def run(self) -> Dict[str, Any]:
        """
        Run all available test suites and return an aggregate result.

        Returns:
            {
                "aggregate_score": float,   # 0.0-1.0
                "suites": {name: {passed, failed, skipped}},
                "failures": [str],
                "duration_ms": float,
                "timestamp": str,
            }
        """
        t0 = time.monotonic()

        if not self._tests_dir.exists():
            logger.warning("No tests directory found. Benchmark returns neutral.")
            return {
                "aggregate_score": 0.5,
                "suites": {},
                "failures": [],
                "duration_ms": 0.0,
                "timestamp": self._now(),
            }

        # Discover test files
        test_files = sorted(self._tests_dir.glob("test_*.py"))
        if not test_files:
            return {
                "aggregate_score": 0.5,
                "suites": {},
                "failures": [],
                "duration_ms": 0.0,
                "timestamp": self._now(),
            }

        suites = {}
        all_failures = []
        total_passed = 0
        total_failed = 0
        total_tests = 0

        for test_file in test_files:
            suite_name = test_file.stem.replace("test_", "")
            result = self._run_suite(test_file)
            suites[suite_name] = result

            total_passed += result.get("passed", 0)
            total_failed += result.get("failed", 0)
            total_tests += result.get("passed", 0) + result.get("failed", 0)
            all_failures.extend(result.get("errors", []))

        # Compute aggregate score
        aggregate = total_passed / total_tests if total_tests > 0 else 0.5
        duration_ms = (time.monotonic() - t0) * 1000

        result = {
            "aggregate_score": round(aggregate, 4),
            "suites": suites,
            "failures": all_failures,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "duration_ms": round(duration_ms, 1),
            "timestamp": self._now(),
        }

        self._last_result = result
        self._save_result(result)
        return result

    def _run_suite(self, test_file: Path) -> Dict[str, Any]:
        """Run a single test file via pytest and parse results."""
        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", str(test_file), "-v", "--tb=short", "-q"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.agent_dir),
            )

            passed = 0
            failed = 0
            skipped = 0
            errors = []

            for line in proc.stdout.splitlines():
                if " passed" in line:
                    try:
                        passed = int(line.split(" passed")[0].strip().split()[-1])
                    except (ValueError, IndexError):
                        pass
                if " failed" in line:
                    try:
                        failed = int(line.split(" failed")[0].strip().split()[-1])
                    except (ValueError, IndexError):
                        pass
                if " skipped" in line:
                    try:
                        skipped = int(line.split(" skipped")[0].strip().split()[-1])
                    except (ValueError, IndexError):
                        pass
                if "FAILED" in line:
                    errors.append(line.strip())

            if proc.returncode != 0 and proc.stderr:
                errors.append(proc.stderr[:500])

            return {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": errors,
            }

        except subprocess.TimeoutExpired:
            return {"passed": 0, "failed": 1, "skipped": 0, "errors": ["Test timed out"]}
        except Exception as e:
            return {"passed": 0, "failed": 1, "skipped": 0, "errors": [str(e)]}

    def _save_result(self, result: Dict[str, Any]) -> None:
        """Save benchmark result for historical comparison."""
        try:
            result_file = self._results_dir / f"benchmark_{int(time.time())}.json"
            result_file.write_text(json.dumps(result, indent=2))

            # Keep only last 50 results
            results = sorted(self._results_dir.glob("benchmark_*.json"))
            for old in results[:-50]:
                old.unlink()
        except Exception as e:
            logger.error(f"Failed to save benchmark result: {e}")

    def get_last_result(self) -> Dict[str, Any]:
        """Return the last benchmark result."""
        return self._last_result

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
