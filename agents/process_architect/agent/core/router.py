"""
agent/core/router.py — Capability router for BlackZero v2.

Reads registry manifests, filters by lifecycle and mode, returns an
explainable routing decision. This is the anti-hardwiring layer for tool
and model selection — nothing in the brain hard-selects implementations.

Usage:
    router = CapabilityRouter(registry_dir)
    decision = router.resolve_tool("shell", mode="act")
    if decision.routable:
        # proceed — decision.manifest has full capability metadata
    else:
        # blocked — decision.reason explains why
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Lifecycle states that are never routed under normal operation.
_BLOCKED_LIFECYCLES = {"quarantined", "retired", "archived"}

# Which modes restrict routing (mode → allowed lifecycle states only)
_MODE_LIFECYCLE_ALLOW = {
    "explore":    {"active", "experimental"},
    "plan":       {"active", "experimental"},
    "act":        {"active"},
    "repair":     {"active", "experimental", "repairable", "quarantined"},
    "audit":      {"active", "experimental", "quarantined", "retired"},
    "quarantine": {"active"},
}


@dataclass
class RoutingDecision:
    routable:      bool
    capability_id: str
    manifest:      dict[str, Any] = field(default_factory=dict)
    reason:        str = ""
    mode:          str = "act"
    satellite_id:  str = ""   # set when the capability is satellite-routed (Fourth Pass)

    def __bool__(self) -> bool:
        return self.routable


class CapabilityRouter:
    """
    Resolves logical capability names to registry manifests.

    Loaded once at agent boot from the registry/ directory.
    All routing decisions are logged for auditability.
    """

    def __init__(self, registry_dir: Path) -> None:
        self._by_id: dict[str, dict] = {}
        self._by_adapter_stem: dict[str, dict] = {}  # last segment of adapter path
        self._by_tool_name: dict[str, dict] = {}     # conventional tool names
        self._load(registry_dir)

    def _load(self, registry_dir: Path) -> None:
        if not registry_dir.exists():
            logger.warning(f"[router] Registry dir not found: {registry_dir}")
            return
        count = 0
        for kind_dir in (registry_dir / "capabilities").iterdir():
            if not kind_dir.is_dir():
                continue
            for yaml_file in kind_dir.glob("*.yaml"):
                try:
                    with open(yaml_file) as f:
                        m = yaml.safe_load(f)
                    if not m or "id" not in m:
                        continue
                    self._by_id[m["id"]] = m
                    # Index by adapter stem (last dot-component of adapter field)
                    adapter = m.get("adapter", "")
                    if adapter:
                        stem = adapter.split(".")[-1]
                        self._by_adapter_stem[stem] = m
                    # Index by conventional short name from yaml filename (no ext)
                    self._by_tool_name[yaml_file.stem] = m
                    count += 1
                except Exception as e:
                    logger.warning(f"[router] Failed to load {yaml_file}: {e}")
        logger.debug(f"[router] Loaded {count} capability manifests")

    def resolve(self, capability_id: str, mode: str = "act") -> RoutingDecision:
        """Resolve a fully-qualified capability id."""
        manifest = self._by_id.get(capability_id)
        if not manifest:
            return RoutingDecision(
                routable=False,
                capability_id=capability_id,
                reason=f"No manifest for capability id: {capability_id}",
                mode=mode,
            )
        return self._check(manifest, mode)

    def resolve_tool(self, tool_name: str, mode: str = "act") -> RoutingDecision:
        """
        Resolve a tool by short name (as the brain uses it).
        Tries: adapter stem → yaml filename → full id prefix.
        """
        manifest = (
            self._by_adapter_stem.get(tool_name)
            or self._by_tool_name.get(tool_name)
            or self._by_adapter_stem.get(f"{tool_name}_tool")  # e.g. "ollama" → "ollama_tool"
        )
        if not manifest:
            # Not finding a manifest is not fatal — unknown tools fall through to executor
            return RoutingDecision(
                routable=True,   # allow — unknown tools handled downstream
                capability_id=f"tool.unknown.{tool_name}",
                manifest={},
                reason="No manifest found — passing through to executor",
                mode=mode,
            )
        return self._check(manifest, mode)

    def _check(self, manifest: dict, mode: str) -> RoutingDecision:
        capability_id = manifest["id"]
        lifecycle = manifest.get("lifecycle", "active")

        # Absolute block regardless of mode
        if lifecycle in _BLOCKED_LIFECYCLES and mode not in ("repair", "audit"):
            reason = f"Lifecycle={lifecycle}: capability is {lifecycle} and cannot be routed"
            logger.warning(f"[router] BLOCKED {capability_id}: {reason}")
            return RoutingDecision(
                routable=False, capability_id=capability_id,
                manifest=manifest, reason=reason, mode=mode,
            )

        # Mode-specific lifecycle filter
        allowed = _MODE_LIFECYCLE_ALLOW.get(mode, {"active"})
        if lifecycle not in allowed:
            reason = f"Lifecycle={lifecycle} not allowed in mode={mode} (allowed: {allowed})"
            logger.warning(f"[router] BLOCKED {capability_id}: {reason}")
            return RoutingDecision(
                routable=False, capability_id=capability_id,
                manifest=manifest, reason=reason, mode=mode,
            )

        # Mode allowed by manifest?
        allowed_modes = manifest.get("allowed_modes", [])
        if allowed_modes and mode not in allowed_modes:
            reason = f"Mode={mode} not in manifest allowed_modes={allowed_modes}"
            logger.warning(f"[router] BLOCKED {capability_id}: {reason}")
            return RoutingDecision(
                routable=False, capability_id=capability_id,
                manifest=manifest, reason=reason, mode=mode,
            )

        logger.debug(f"[router] ROUTED {capability_id} via mode={mode}")
        return RoutingDecision(
            routable=True, capability_id=capability_id,
            manifest=manifest,
            reason=f"lifecycle={lifecycle}, mode={mode} — OK",
            mode=mode,
        )

    def list_tools(self, mode: str = "act") -> list[dict]:
        """Return all routable tool manifests for a given mode."""
        return [
            m for m in self._by_id.values()
            if m.get("kind") == "tool" and self._check(m, mode).routable
        ]

    def get(self, capability_id: str) -> dict | None:
        return self._by_id.get(capability_id)
