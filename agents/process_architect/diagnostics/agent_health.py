"""
agent_health.py — Concrete HealthCheck implementation.

Stamped from BlackZero. Works out of the box — gracefully handles
subsystems that aren't wired (e.g. vector store is optional).

Usage:
    from diagnostics.agent_health import AgentHealthCheck
    hc = AgentHealthCheck(model_router=router, memory_manager=memory)
    report = hc.check_all()
"""
from __future__ import annotations

from diagnostics.healthcheck import HealthCheck, HealthStatus, SubsystemResult


class AgentHealthCheck(HealthCheck):
    """
    Concrete health check. Checks what's wired; reports DEGRADED (not UNHEALTHY)
    for optional subsystems that aren't present.
    """

    def __init__(
        self,
        model_router=None,
        memory_manager=None,
        tool_registry=None,
        vector_store=None,
        sqlite_store=None,
    ) -> None:
        self._model_router   = model_router
        self._memory_manager = memory_manager
        self._tool_registry  = tool_registry
        self._vector_store   = vector_store
        self._sqlite_store   = sqlite_store

    def check_model_provider(self) -> SubsystemResult:
        if self._model_router is None:
            return SubsystemResult("model_provider", HealthStatus.UNHEALTHY,
                                   "no model_router wired")
        try:
            providers = self._model_router.list_providers()
            if not providers:
                return SubsystemResult("model_provider", HealthStatus.UNHEALTHY,
                                       "list_providers() returned empty")
            # Check if any provider is reachable
            available = getattr(self._model_router, "is_available", lambda: True)()
            status = HealthStatus.HEALTHY if available else HealthStatus.DEGRADED
            msg    = f"providers={providers}" + ("" if available else " (Ollama unreachable, fallback active)")
            return SubsystemResult("model_provider", status, msg)
        except Exception as e:
            return SubsystemResult("model_provider", HealthStatus.UNHEALTHY, str(e))

    def check_vector_store(self) -> SubsystemResult:
        if self._vector_store is None:
            # Optional subsystem — not wired means no vector search, not a failure
            return SubsystemResult("vector_store", HealthStatus.DEGRADED,
                                   "not wired (optional — keyword search only)")
        try:
            # Attempt a no-op probe
            self._vector_store.search([], top_k=1)
            return SubsystemResult("vector_store", HealthStatus.HEALTHY)
        except Exception as e:
            return SubsystemResult("vector_store", HealthStatus.UNHEALTHY, str(e))

    def check_sqlite_store(self) -> SubsystemResult:
        if self._sqlite_store is None and self._memory_manager is None:
            return SubsystemResult("sqlite_store", HealthStatus.UNHEALTHY,
                                   "no sqlite_store or memory_manager wired")
        try:
            # Use memory_manager's db path if available (SQLiteMemoryManager exposes stats)
            if self._memory_manager is not None and hasattr(self._memory_manager, "stats"):
                stats = self._memory_manager.stats()
                return SubsystemResult("sqlite_store", HealthStatus.HEALTHY,
                                       f"db={stats.get('db_path', '?')}, entries={stats.get('total', '?')}")
            return SubsystemResult("sqlite_store", HealthStatus.HEALTHY)
        except Exception as e:
            return SubsystemResult("sqlite_store", HealthStatus.UNHEALTHY, str(e))

    def check_memory_manager(self) -> SubsystemResult:
        if self._memory_manager is None:
            return SubsystemResult("memory_manager", HealthStatus.UNHEALTHY,
                                   "no memory_manager wired")
        try:
            # Write + read round-trip
            from memory.memory_schema import MemorySource
            mid = self._memory_manager.add_memory(
                "__health_probe__",
                source=MemorySource.INFERENCE,
                importance=0.01,
            )
            rec = self._memory_manager.get_memory(mid)
            self._memory_manager.delete_memory(mid)
            if rec is None:
                return SubsystemResult("memory_manager", HealthStatus.UNHEALTHY,
                                       "write succeeded but read returned None")
            return SubsystemResult("memory_manager", HealthStatus.HEALTHY, "round-trip ok")
        except Exception as e:
            return SubsystemResult("memory_manager", HealthStatus.UNHEALTHY, str(e))

    def check_tool_registry(self) -> SubsystemResult:
        if self._tool_registry is None:
            return SubsystemResult("tool_registry", HealthStatus.DEGRADED,
                                   "no tool_registry wired (optional)")
        try:
            count = len(self._tool_registry)
            status = HealthStatus.HEALTHY if count > 0 else HealthStatus.DEGRADED
            msg    = f"{count} tool(s) registered"
            return SubsystemResult("tool_registry", status, msg)
        except Exception as e:
            return SubsystemResult("tool_registry", HealthStatus.UNHEALTHY, str(e))
