# healthcheck.py
# RUNTIME HEALTH CHECKER
#
# Responsibility:
#   Checks the runtime health of a running agent instance.
#   Complements doctor.py (which checks structure) by checking live state.
#
# Usage:
#   python BlackZero/diagnostics/healthcheck.py
#
# NOTE: This file defines the HealthCheck interface. A concrete agent
#       subclasses HealthCheck and wires in its own subsystem instances.

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class SubsystemResult:
    name: str
    status: HealthStatus
    message: str = ""

    def ok(self) -> bool:
        return self.status == HealthStatus.HEALTHY


class HealthCheck(ABC):
    """
    Abstract base class for agent runtime health checks.

    Agents subclass HealthCheck and implement each check_*() method
    to verify their specific subsystem instances. check_all() aggregates
    results and determines the overall status.

    Example agent implementation:
        class EngineerHealthCheck(HealthCheck):
            def __init__(self, model_router, vector_store):
                self._router = model_router
                self._vstore = vector_store

            def check_model_provider(self):
                ok = self._router.list_providers() != []
                return SubsystemResult(
                    name="model_provider",
                    status=HealthStatus.HEALTHY if ok else HealthStatus.UNHEALTHY,
                )
    """

    @abstractmethod
    def check_model_provider(self) -> SubsystemResult:
        """Verify that at least one model provider is reachable."""

    @abstractmethod
    def check_vector_store(self) -> SubsystemResult:
        """Verify that the vector store is accessible and responsive."""

    @abstractmethod
    def check_sqlite_store(self) -> SubsystemResult:
        """Verify that the SQLite database is accessible and not corrupt."""

    @abstractmethod
    def check_memory_manager(self) -> SubsystemResult:
        """Verify the memory system is operational (write + read round-trip)."""

    @abstractmethod
    def check_tool_registry(self) -> SubsystemResult:
        """Verify the tool registry is loaded and has at least one tool."""

    def check_all(self) -> dict:
        """
        Run all health checks and return a structured report.

        Returns:
            {
                "overall": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
                "subsystems": [
                    {"name": str, "status": str, "message": str},
                    ...
                ]
            }
        """
        checks = [
            self.check_model_provider,
            self.check_vector_store,
            self.check_sqlite_store,
            self.check_memory_manager,
            self.check_tool_registry,
        ]
        results: list[SubsystemResult] = []
        for check in checks:
            try:
                result = check()
            except Exception as e:
                result = SubsystemResult(
                    name=check.__name__,
                    status=HealthStatus.UNHEALTHY,
                    message=f"check raised unexpected error: {e}",
                )
            results.append(result)

        statuses = {r.status for r in results}
        if HealthStatus.UNHEALTHY in statuses:
            overall = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return {
            "overall": overall.value,
            "subsystems": [
                {"name": r.name, "status": r.status.value, "message": r.message}
                for r in results
            ],
        }


if __name__ == "__main__":
    print("healthcheck.py: no concrete agent wired in — instantiate a HealthCheck subclass.")
    sys.exit(0)
