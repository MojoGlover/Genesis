"""
loader.py — BlackZero Module Loader

Boot sequence: config → discover → setup() → wire → CognitiveLoop

Every agent calls:
    from BlackZero.loader import boot
    loop = boot("config.yaml", "modules/")
    loop.run()

Module contract:
    Each module is a subdirectory in modules/ containing a module.py that exports:
        def setup(config: dict) -> dict
    The returned dict maps slot names to implementations:
        "model_router"   → ModelRouter instance
        "memory_manager" → MemoryManager instance
        "retriever"      → Retriever instance
        "policy_filter"  → PolicyFilter instance
        "tools"          → list[BaseTool] instances
        "sinks"          → dict[channel_name, callable]
        "error_sink"     → callable
        "input_feed"     → callable(router) — called post-wire to attach input sources

NOTE: This file is part of the BlackZero framework.
      Do not add agent-specific logic here.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from BlackZero.brain.loop import CognitiveLoop
from BlackZero.brain.planner import Planner
from BlackZero.brain.executor import Executor, PolicyFilter
from BlackZero.brain.router import Router
from BlackZero.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# Slot classification for merge behavior
_SINGLETON_SLOTS = {"model_router", "memory_manager", "retriever", "policy_filter", "error_sink", "plugops_client"}
_LIST_SLOTS = {"tools", "input_feed"}
_DICT_SLOTS = {"sinks", "config_overrides"}
_ALL_KNOWN = _SINGLETON_SLOTS | _LIST_SLOTS | _DICT_SLOTS


def boot(config_path: str, modules_dir: Optional[str] = None) -> CognitiveLoop:
    """
    Full boot sequence. Called by the agent's main.py.

    Args:
        config_path:  Path to config.yaml
        modules_dir:  Path to modules/ directory (default: sibling of config)

    Returns:
        A wired, runnable CognitiveLoop.
    """
    config_path = Path(config_path).resolve()
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    if modules_dir is None:
        modules_dir = config_path.parent / "modules"
    else:
        modules_dir = Path(modules_dir).resolve()

    return _wire(config, modules_dir)


def boot_from_dict(config: dict, modules_dir: Optional[str] = None) -> CognitiveLoop:
    """Same as boot(), but accepts a pre-loaded config dict. Useful for tests."""
    md = Path(modules_dir).resolve() if modules_dir else None
    return _wire(config, md)


def _wire(config: dict, modules_dir: Optional[Path]) -> CognitiveLoop:
    """Internal: discover modules, build subsystems, wire brain, return loop."""

    # 1. Discover and load modules
    slots = _discover_and_load(modules_dir, config) if modules_dir else {}

    # 2. Build ToolRegistry
    tool_registry = ToolRegistry()
    for tool in slots.get("tools", []):
        try:
            tool_registry.register(tool)
        except ValueError as e:
            logger.warning(f"Skipping duplicate tool: {e}")

    # 3. Resolve data directory for weight persistence
    data_dir = Path(config.get("data_dir", "~/.blackzero")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    # 4. Build brain components
    planner = Planner(weights_path=data_dir / "strategy_weights.json")

    executor = Executor(
        model_router=slots.get("model_router"),
        tool_registry=tool_registry if len(tool_registry) > 0 else None,
        memory_manager=slots.get("memory_manager"),
        retriever=slots.get("retriever"),
        policy_filter=slots.get("policy_filter"),
    )

    router = Router(config=config)

    # 5. Wire I/O sinks
    for channel, sink in slots.get("sinks", {}).items():
        router.register_sink(channel, sink)
    if "error_sink" in slots:
        router.register_error_sink(slots["error_sink"])
    # Ensure at least a default sink so output never vanishes
    if not router._output_sinks:
        router.register_sink("default", print)

    # 6. Merge config overrides from modules
    config.update(slots.get("config_overrides", {}))

    # 7. Post-wire: attach input feeds (they need the router reference)
    for feed_fn in slots.get("input_feed", []):
        try:
            feed_fn(router)
        except Exception as e:
            logger.error(f"Input feed attach failed: {e}")

    # 8. Build loop
    loop = CognitiveLoop(
        planner=planner,
        executor=executor,
        router=router,
        config=config,
    )

    logger.info(
        f"Boot complete. "
        f"model_router={'yes' if slots.get('model_router') else 'no'} | "
        f"memory={'yes' if slots.get('memory_manager') else 'no'} | "
        f"retriever={'yes' if slots.get('retriever') else 'no'} | "
        f"tools={len(tool_registry)} | "
        f"sinks={list(router._output_sinks.keys())}"
    )

    # 9. Wire module reload function into plugops bridge if present
    plugops_client = slots.get("plugops_client")
    if plugops_client and hasattr(plugops_client, "set_reload_fn"):
        def _reload_module(module_name: str) -> dict:
            return _reload_single_module(module_name, modules_dir, config, executor, router)
        plugops_client.set_reload_fn(_reload_module)
        logger.info("Boot: plugops bridge reload function wired")

    return loop


def _reload_single_module(
    module_name: str,
    modules_dir: Path,
    config: dict,
    executor,
    router,
) -> dict:
    """
    Re-run a single module's setup() and wire new slots into the running brain.

    Called by the plugops_bridge reload function after Cerberus activates a module.
    Supports hot-wiring model_router, memory_manager, and output sinks without
    restarting the full boot sequence.

    Args:
        module_name: Name of the module subdirectory under modules_dir.
        modules_dir: Path to the modules directory.
        config:      Current agent config dict.
        executor:    Running Executor instance — receives model_router / memory_manager updates.
        router:      Running Router instance — receives new sinks.

    Returns:
        The slot dict returned by the module's setup(), or {} on failure.

    Raises:
        FileNotFoundError: If the module directory or module.py does not exist.
    """
    if modules_dir is None:
        raise FileNotFoundError(f"No modules_dir configured; cannot reload '{module_name}'")

    module_file = modules_dir / module_name / "module.py"
    if not module_file.exists():
        raise FileNotFoundError(f"Module not found: {module_name}")

    spec = importlib.util.spec_from_file_location(
        f"modules.{module_name}.module", module_file
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.setup(config)
    if not isinstance(result, dict):
        return {}

    # Wire new slots into the running brain
    if "model_router" in result:
        executor._model_router = result["model_router"]
    if "memory_manager" in result:
        executor._memory_manager = result["memory_manager"]
    for channel, sink in result.get("sinks", {}).items():
        router.register_sink(channel, sink)

    logger.info(f"Reloaded module: {module_name} → {list(result.keys())}")
    return result


def _discover_and_load(modules_dir: Path, config: dict) -> dict:
    """
    Scan modules_dir for subdirectories containing module.py.
    Import each, call setup(config), accumulate slot mappings.
    """
    if not modules_dir.exists():
        logger.warning(f"Modules directory not found: {modules_dir}")
        return {}

    slots: dict[str, Any] = {}

    for entry in sorted(modules_dir.iterdir()):
        if not entry.is_dir():
            continue
        module_file = entry / "module.py"
        if not module_file.exists():
            continue

        name = entry.name
        try:
            spec = importlib.util.spec_from_file_location(
                f"modules.{name}.module", module_file
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            setup_fn = getattr(mod, "setup", None)
            if setup_fn is None:
                logger.warning(f"Module '{name}' has no setup() function, skipping.")
                continue

            result = setup_fn(config)
            if not isinstance(result, dict):
                logger.warning(
                    f"Module '{name}' setup() returned {type(result).__name__}, "
                    f"expected dict. Skipping."
                )
                continue

            # Merge into accumulated slots
            for key, value in result.items():
                if key in _LIST_SLOTS:
                    slots.setdefault(key, [])
                    if isinstance(value, list):
                        slots[key].extend(value)
                    else:
                        slots[key].append(value)
                elif key in _DICT_SLOTS:
                    slots.setdefault(key, {}).update(value)
                elif key in _SINGLETON_SLOTS:
                    if key in slots:
                        logger.warning(
                            f"Module '{name}' overrides slot '{key}' (previously set)."
                        )
                    slots[key] = value
                else:
                    logger.warning(
                        f"Module '{name}' returned unknown slot '{key}', ignoring."
                    )

            logger.info(f"Loaded module: {name} → {list(result.keys())}")

        except Exception:
            logger.exception(f"Failed to load module '{name}', skipping.")

    return slots
