"""
GENESIS ModuleRegistry — Discovers, validates, mounts, and manages capability modules.

Discovery contract:
    Every directory under modules/ that contains a module.py with a class
    named `Module` subclassing ModuleBase is auto-discovered at startup.

    modules/
        sdimport/
            module.py    <- class Module(ModuleBase): ...
        vision/
            module.py    <- class Module(ModuleBase): ...

Startup (called from app.py lifespan, AFTER init_monitoring):
    registry = get_module_registry()
    await registry.mount_all(app)

Teardown (called from app.py lifespan):
    await registry.shutdown_all()

Adding a new module:
    1. Create modules/<name>/module.py with class Module(ModuleBase)
    2. Restart GENESIS
    3. Done — app.py is never touched
"""

from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException

from agents.tools.tool_registry import get_registry as get_tool_registry
from core.monitoring.registry import get_agent_registry
from core.modules.base import ModuleBase

logger = logging.getLogger(__name__)

# Default: modules/ directory at GENESIS project root
_MODULES_DIR = Path(__file__).parent.parent.parent / "modules"


class ModuleRegistry:
    """
    Singleton registry for all GENESIS capability modules.

    Thread-safety: discover/mount run at startup (single-threaded).
    get_module() and list_modules() are read-only and always safe to call.
    """

    _instance: Optional[ModuleRegistry] = None
    _class_lock = threading.Lock()

    def __new__(cls) -> ModuleRegistry:
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._modules: Dict[str, ModuleBase] = {}
        self._mount_errors: Dict[str, str] = {}
        self._initialized = True
        logger.info("ModuleRegistry initialized")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, modules_dir: Optional[Path] = None) -> List[ModuleBase]:
        """
        Walk modules_dir, import every module.py, instantiate Module().

        Args:
            modules_dir: Override the default path (useful in tests).

        Returns:
            List of successfully loaded ModuleBase instances.
            Errors per directory are logged and stored in self._mount_errors.
        """
        base = modules_dir or _MODULES_DIR
        loaded: List[ModuleBase] = []

        if not base.exists():
            logger.warning(f"[ModuleRegistry] Modules directory not found: {base}")
            return loaded

        for module_dir in sorted(base.iterdir()):
            if not module_dir.is_dir() or module_dir.name.startswith("_"):
                continue

            module_file = module_dir / "module.py"
            if not module_file.exists():
                continue

            try:
                instance = self._load_module_file(module_file, module_dir.name)
                loaded.append(instance)
                logger.info(
                    f"[ModuleRegistry] Discovered: {instance.name} v{instance.version}"
                )
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                logger.error(
                    f"[ModuleRegistry] Failed to load {module_file}: {err}"
                )
                self._mount_errors[module_dir.name] = err

        return loaded

    def _load_module_file(self, module_file: Path, dir_name: str) -> ModuleBase:
        """
        Import module_file, find class Module, validate it, return an instance.

        Raises:
            AttributeError: No class named 'Module' in the file.
            TypeError:      'Module' does not subclass ModuleBase.
            Exception:      Module() constructor raised.
        """
        spec = importlib.util.spec_from_file_location(
            f"modules.{dir_name}.module", module_file
        )
        py_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(py_module)

        cls = getattr(py_module, "Module")
        if not (isinstance(cls, type) and issubclass(cls, ModuleBase)):
            raise TypeError(
                f"'Module' in {module_file} must subclass ModuleBase, got {cls!r}"
            )

        return cls()

    # ------------------------------------------------------------------
    # Mounting
    # ------------------------------------------------------------------

    async def mount_all(self, app: FastAPI) -> None:
        """
        Primary startup entry point called from app.py lifespan.

        Per discovered module:
          1. Validate name is unique
          2. app.include_router(module.router)
          3. Validate tools exist in ToolRegistry
          4. Register + start agents in AgentRegistry
          5. await module.on_startup()
          6. Store in self._modules

        Then mounts the /modules meta-endpoints.
        """
        modules = self.discover()

        for mod in modules:
            try:
                await self._mount_one(app, mod)
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                logger.error(
                    f"[ModuleRegistry] Module '{mod.name}' failed during mount: {err}"
                )
                self._mount_errors[mod.name] = err

        self._mount_meta_router(app)

        total = len(self._modules)
        failed = len(self._mount_errors)
        logger.info(
            f"[ModuleRegistry] {total} module(s) mounted, {failed} failed"
        )

    async def _mount_one(self, app: FastAPI, mod: ModuleBase) -> None:
        """Mount a single validated module."""
        if mod.name in self._modules:
            raise ValueError(
                f"Duplicate module name '{mod.name}'. Module names must be unique."
            )

        # 1. Mount HTTP router
        app.include_router(mod.router)
        logger.debug(f"[{mod.name}] Router mounted")

        # 2. Validate tools
        if mod.tools:
            tool_registry = get_tool_registry()
            for fn in mod.tools:
                fn_name = getattr(fn, "__name__", repr(fn))
                if fn_name not in tool_registry.tools:
                    logger.warning(
                        f"[{mod.name}] Tool '{fn_name}' not found in ToolRegistry. "
                        f"Ensure it is decorated with @register_tool."
                    )
            logger.debug(f"[{mod.name}] {len(mod.tools)} tool(s) verified")

        # 3. Register and start agents
        if mod.agents:
            agent_registry = get_agent_registry()
            for agent in mod.agents:
                agent_registry.register(agent)
                agent.start()
            logger.debug(f"[{mod.name}] {len(mod.agents)} agent(s) registered")

        # 4. Startup hook
        await mod.on_startup()
        logger.debug(f"[{mod.name}] on_startup() complete")

        # 5. Store
        self._modules[mod.name] = mod
        logger.info(f"[ModuleRegistry] Module '{mod.name}' mounted successfully")

    def _mount_meta_router(self, app: FastAPI) -> None:
        """
        Mount /modules and /modules/{name}/health after all modules are registered
        so the closure captures the final state of self._modules.
        """
        meta = APIRouter(prefix="/modules", tags=["modules"])

        @meta.get("")
        async def list_modules() -> Dict[str, Any]:
            """List all registered modules with metadata and live health."""
            result: Dict[str, Any] = {}
            for name, mod in self._modules.items():
                entry = mod.to_dict()
                try:
                    entry["health"] = mod.health()
                except Exception as exc:
                    entry["health"] = {"status": "error", "error": str(exc)}
                result[name] = entry
            return {
                "modules": result,
                "total":   len(result),
                "errors":  self._mount_errors,
            }

        @meta.get("/{module_name}/health")
        async def module_health(module_name: str) -> Dict[str, Any]:
            """Health check for a single module."""
            mod = self._modules.get(module_name)
            if mod is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Module '{module_name}' not found",
                )
            try:
                return mod.health()
            except Exception as exc:
                return {"status": "error", "module": module_name, "error": str(exc)}

        app.include_router(meta)
        logger.debug("[ModuleRegistry] Meta-router mounted at /modules")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown_all(self) -> None:
        """
        Called from app.py lifespan teardown (before shutdown_monitoring).

        For each mounted module: stop agents, then call on_shutdown().
        Errors per module are logged but do not block teardown of others.
        """
        agent_registry = get_agent_registry()

        for name, mod in self._modules.items():
            try:
                for agent in mod.agents:
                    try:
                        agent.stop()
                    except Exception as exc:
                        logger.warning(
                            f"[{name}] Error stopping agent '{agent.name}': {exc}"
                        )
                await mod.on_shutdown()
                logger.info(f"[ModuleRegistry] Module '{name}' shut down")
            except Exception as exc:
                logger.error(f"[ModuleRegistry] Error shutting down '{name}': {exc}")

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_module(self, name: str) -> Optional[ModuleBase]:
        """Return a mounted module by slug, or None."""
        return self._modules.get(name)

    def list_modules(self) -> List[str]:
        """Return sorted list of mounted module names."""
        return sorted(self._modules.keys())

    def get_all_modules(self) -> Dict[str, ModuleBase]:
        """Return a copy of the mounted modules dict."""
        return dict(self._modules)

    def get_mount_errors(self) -> Dict[str, str]:
        """Return modules that failed to mount, keyed by directory name."""
        return dict(self._mount_errors)

    def get_stats(self) -> Dict[str, Any]:
        """Registry summary for diagnostics."""
        return {
            "mounted": len(self._modules),
            "failed":  len(self._mount_errors),
            "modules": self.list_modules(),
            "errors":  self._mount_errors,
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_registry: Optional[ModuleRegistry] = None


def get_module_registry() -> ModuleRegistry:
    """Get (or create) the global ModuleRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry
