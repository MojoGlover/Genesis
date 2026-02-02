"""
GENESIS Engineer X (Engineer 10)

Role: Tester
Autonomous agent that ensures code quality through automated testing.

Features:
- Runs pytest, flake8, black, mypy
- Tracks test results over time
- Alerts on critical failures
- Fully autonomous (no approval needed)
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.framework import AgentBase, AgentConfig
from core.messaging import Message, MessageType
from core.monitoring import get_alert_system, AlertSeverity, get_error_logger

from .test_runner import TestRunner, TestSuiteResult

logger = logging.getLogger(__name__)


class EngineerX(AgentBase):
    """
    Engineer X (Engineer 10) - Tester

    Runs tests on schedule or on-demand, tracks results,
    and alerts on failures. Part of Engineer 0's team.
    """

    def __init__(self, project_root: Optional[Path] = None, config_path: Optional[Path] = None):
        # Load config
        config_path = config_path or Path(__file__).parent / "config.json"
        config = AgentConfig.from_file(config_path)

        super().__init__(config)

        # Identity
        self.designation = "Engineer 10"
        self.alias = "X"
        self.role = "Tester"

        # Project settings
        self.project_root = project_root or Path.home() / "ai/GENESIS"
        self.runner = TestRunner(self.project_root)

        # Test history
        self._test_history: List[Dict[str, Any]] = []
        self._max_history = 100

        # Last run times for scheduling
        self._last_runs: Dict[str, datetime] = {}

    def execute_task(self, task: Dict[str, Any]) -> Any:
        """
        Execute a testing task.

        Task types:
        - run_all: Run all test suites
        - run_pytest: Run pytest only
        - run_lint: Run flake8 only
        - run_typecheck: Run mypy only
        - run_format: Run black check
        - get_history: Get test history
        - get_status: Get current test status
        """
        task_type = task.get("type", "run_all")

        if task_type == "run_all":
            return self._run_all_tests()
        elif task_type == "run_pytest":
            return self._run_pytest(task.get("path", "tests/"))
        elif task_type == "run_lint":
            return self._run_lint()
        elif task_type == "run_typecheck":
            return self._run_typecheck()
        elif task_type == "run_format":
            return self._run_format(check_only=task.get("check_only", True))
        elif task_type == "get_history":
            return self._get_history(task.get("limit", 20))
        elif task_type == "get_status":
            return self._get_status()
        else:
            raise ValueError(f"Unknown task type: {task_type}")

    def _run_all_tests(self) -> Dict[str, Any]:
        """Run all test suites and quality checks."""
        logger.info(f"[{self.alias}] Running all tests...")

        result = self.runner.run_all()
        self._record_result("all", result)

        # Check for failures
        if not result["success"]:
            self._handle_test_failure(result)

        self._last_runs["all"] = datetime.now()
        return result

    def _run_pytest(self, path: str = "tests/") -> Dict[str, Any]:
        """Run pytest on specified path."""
        logger.info(f"[{self.alias}] Running pytest on {path}...")

        result = self.runner.run_pytest(path)
        result_dict = result.to_dict()
        self._record_result("pytest", result_dict)

        if not result.success:
            self._handle_test_failure({"pytest": result_dict})

        self._last_runs["pytest"] = datetime.now()
        return result_dict

    def _run_lint(self) -> Dict[str, Any]:
        """Run flake8 linting."""
        logger.info(f"[{self.alias}] Running flake8...")

        result = self.runner.run_flake8()
        result_dict = result.to_dict()
        self._record_result("flake8", result_dict)

        self._last_runs["lint"] = datetime.now()
        return result_dict

    def _run_typecheck(self) -> Dict[str, Any]:
        """Run mypy type checking."""
        logger.info(f"[{self.alias}] Running mypy...")

        result = self.runner.run_mypy()
        result_dict = result.to_dict()
        self._record_result("mypy", result_dict)

        self._last_runs["typecheck"] = datetime.now()
        return result_dict

    def _run_format(self, check_only: bool = True) -> Dict[str, Any]:
        """Run black code formatter."""
        logger.info(f"[{self.alias}] Running black...")

        result = self.runner.run_black(check_only=check_only)
        result_dict = result.to_dict()
        self._record_result("black", result_dict)

        self._last_runs["format"] = datetime.now()
        return result_dict

    def _get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get test history."""
        return self._test_history[-limit:]

    def _get_status(self) -> Dict[str, Any]:
        """Get current testing status."""
        return {
            "agent": self.name,
            "designation": self.designation,
            "alias": self.alias,
            "role": self.role,
            "health": self._health_status.value,
            "last_runs": {k: v.isoformat() for k, v in self._last_runs.items()},
            "history_count": len(self._test_history),
            "last_result": self._test_history[-1] if self._test_history else None,
        }

    def _record_result(self, suite: str, result: Dict[str, Any]) -> None:
        """Record a test result in history."""
        entry = {
            "suite": suite,
            "timestamp": datetime.now().isoformat(),
            "result": result,
        }
        self._test_history.append(entry)

        # Trim history
        if len(self._test_history) > self._max_history:
            self._test_history = self._test_history[-self._max_history:]

    def _handle_test_failure(self, result: Dict[str, Any]) -> None:
        """Handle test failures - log and alert."""
        # Log error
        error_logger = get_error_logger()
        error_logger.log_error(
            agent=self.name,
            error="Test suite failed",
            context={"result": result},
        )

        # Count failures
        total_failures = 0
        failure_details = []

        for suite_name, suite_result in result.get("results", result).items():
            if isinstance(suite_result, dict):
                if suite_result.get("status") == "failed" or not suite_result.get("success", True):
                    total_failures += 1
                    failure_details.append(f"{suite_name}: {suite_result.get('failed', 0)} failed")

        # Send alert
        alert_system = get_alert_system()

        if total_failures > 3:
            # Critical - many failures
            alert_system.send_alert(
                severity=AlertSeverity.CRITICAL,
                agent=self.name,
                message=f"[{self.alias}] Multiple test suites failing: {', '.join(failure_details)}",
                context={"failures": total_failures},
            )
        elif total_failures > 0:
            # Degraded - some failures
            alert_system.send_alert(
                severity=AlertSeverity.DEGRADED,
                agent=self.name,
                message=f"[{self.alias}] Test failures detected: {', '.join(failure_details)}",
                context={"failures": total_failures},
            )

    def get_health_details(self) -> Dict[str, Any]:
        """Override to include test-specific health info."""
        base = super().get_health_details()

        # Add identity
        base["designation"] = self.designation
        base["alias"] = self.alias
        base["role"] = self.role

        # Add test-specific info
        base["last_runs"] = {k: v.isoformat() for k, v in self._last_runs.items()}
        base["test_history_count"] = len(self._test_history)

        if self._test_history:
            last = self._test_history[-1]
            base["last_test"] = {
                "suite": last["suite"],
                "timestamp": last["timestamp"],
                "success": last["result"].get("success", False),
            }

        return base


# Factory function
def create_engineer_x(project_root: Optional[Path] = None) -> EngineerX:
    """Create and return Engineer X instance."""
    agent = EngineerX(project_root=project_root)
    return agent


# Standalone execution
if __name__ == "__main__":
    import sys

    agent = create_engineer_x()
    agent.start()

    # Run all tests if executed directly
    if len(sys.argv) > 1:
        task_type = sys.argv[1]
    else:
        task_type = "run_all"

    result = agent.execute_task({"type": task_type})
    print(json.dumps(result, indent=2, default=str))

    agent.stop()
