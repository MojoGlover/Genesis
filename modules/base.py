"""
GENESIS ModuleBase — Abstract interface every capability module must implement.

A module is a self-contained unit that contributes:
  - HTTP routes  (FastAPI APIRouter)
  - Tools        (registered in ToolRegistry)
  - Agents       (registered in AgentRegistry)
  - Lifecycle    (on_startup / on_shutdown coroutines)
  - Health       (synchronous status dict)

Convention:
  modules/<name>/module.py must contain exactly one class named `Module`
  that subclasses ModuleBase.

Example minimal module:

    # modules/hello/module.py
    from fastapi import APIRouter
    from modules.base import ModuleBase

    class Module(ModuleBase):
        @property
        def name(self) -> str: return "hello"
        @property
        def version(self) -> str: return "1.0.0"
        @property
        def description(self) -> str: return "Says hello."
        @property
        def router(self) -> APIRouter:
            r = APIRouter(prefix="/hello", tags=["hello"])
            @r.get("/ping")
            async def ping(): return {"pong": True}
            return r
        def health(self): return {"status": "ok", "module": self.name, "version": self.version}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from fastapi import APIRouter


class ModuleBase(ABC):
    """
    Abstract base class for all GENESIS capability modules.

    Subclasses MUST implement:
        name        (@property str)
        version     (@property str)
        description (@property str)
        router      (@property APIRouter)
        health()    (method → dict)

    Subclasses MAY override:
        tags        (@property List[str])  — defaults to [self.name]
        tools       (@property List)       — defaults to []
        agents      (@property List)       — defaults to []
        on_startup  (async method)         — defaults to no-op
        on_shutdown (async method)         — defaults to no-op
    """

    # ------------------------------------------------------------------
    # Required identity — must be implemented by every module
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique slug for this module.
        Used as the URL prefix and registry key.
        Must be lowercase, no spaces (e.g. "sdimport", "vision", "scheduler").
        """
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """SemVer string, e.g. '1.0.0'."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-sentence human-readable description."""
        ...

    # ------------------------------------------------------------------
    # Optional identity — override as needed
    # ------------------------------------------------------------------

    @property
    def tags(self) -> List[str]:
        """OpenAPI tags for all routes. Defaults to [self.name]."""
        return [self.name]

    # ------------------------------------------------------------------
    # Required HTTP integration
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def router(self) -> APIRouter:
        """
        The APIRouter containing all HTTP endpoints for this module.
        The registry mounts this via app.include_router(module.router).

        Build the router with prefix="/<module_name>" so all routes are
        scoped under /sdimport/..., /vision/..., etc.
        """
        ...

    # ------------------------------------------------------------------
    # Optional ToolRegistry integration
    # ------------------------------------------------------------------

    @property
    def tools(self) -> List[Any]:
        """
        Callable tool functions already decorated with @register_tool.
        The registry validates they exist in the global ToolRegistry.
        Return [] if this module has no tools.
        """
        return []

    # ------------------------------------------------------------------
    # Optional AgentRegistry integration
    # ------------------------------------------------------------------

    @property
    def agents(self) -> List[Any]:
        """
        AgentBase instances owned by this module.
        The registry calls agent.start() at mount and agent.stop() at shutdown.
        Return [] if this module has no agents.
        """
        return []

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """
        Called after the router is mounted and agents are started.
        Use for async I/O initialization: DB connections, model loading, etc.
        Errors here are logged and re-raised, halting startup for this module.
        """
        pass

    async def on_shutdown(self) -> None:
        """
        Called before the process exits (lifespan teardown).
        Use for connection cleanup, flushing buffers, etc.
        Errors are logged but do NOT prevent other modules from shutting down.
        """
        pass

    # ------------------------------------------------------------------
    # Required health reporting
    # ------------------------------------------------------------------

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """
        Return a synchronous health snapshot served at GET /modules/{name}/health.

        Required keys:
            {
                "status":  "ok" | "degraded" | "error",
                "module":  self.name,
                "version": self.version,
            }

        Add any module-specific fields (last_run, cache_size, error_count, etc.).
        """
        ...

    # ------------------------------------------------------------------
    # Serialization — do not override
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize module metadata for the GET /modules endpoint."""
        return {
            "name":        self.name,
            "version":     self.version,
            "description": self.description,
            "tags":        self.tags,
            "routes": [
                {
                    "path":    route.path,
                    "methods": sorted(route.methods or []),
                }
                for route in self.router.routes
                if hasattr(route, "methods")
            ],
            "tool_count":  len(self.tools),
            "agent_count": len(self.agents),
        }

    def __repr__(self) -> str:
        return f"Module({self.name} v{self.version})"
