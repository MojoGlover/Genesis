"""
module_manifest.py — Module manifest registry.

Each module declares a MANIFEST describing what it needs and what it provides.
The loader collects these to build the agent's registration payload for Cerberus.

A MANIFEST is a plain dict with keys such as:
    name                — module identifier
    description         — human-readable purpose
    requires_credentials — list of credential keys required before activation
    optional_credentials — list of credential keys that enhance behaviour if present
    requires_config     — list of config keys that must be present
    provides            — list of slot/capability names this module exports
    capabilities        — list of high-level capability labels
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """
    Central registry for module manifests and activation state.

    Modules call registry.register() during their setup() to announce
    their presence. The plugops_bridge reads the registry to build the
    agent_manifest payload sent to Cerberus.
    """

    def __init__(self) -> None:
        self._modules: dict[str, dict] = {}

    def register(self, module_name: str, manifest: dict, status: str = "pending") -> None:
        """
        Register a module with its manifest and initial status.

        Args:
            module_name: Unique identifier for the module.
            manifest:    Plain dict describing the module (see MANIFEST convention).
            status:      "active" for modules that self-activate on boot;
                         "pending" for modules awaiting Cerberus credentials.
        """
        if status not in ("active", "pending"):
            logger.warning(
                f"ModuleRegistry: unknown status '{status}' for '{module_name}', defaulting to 'pending'"
            )
            status = "pending"

        entry = dict(manifest)
        entry["status"] = status
        self._modules[module_name] = entry
        logger.debug(f"ModuleRegistry: registered '{module_name}' status={status}")

    def get_all(self) -> dict:
        """Return a shallow copy of all registered modules with their manifests and status."""
        return dict(self._modules)

    def get_pending(self) -> list[str]:
        """Return names of modules that are registered but not yet activated."""
        return [
            name
            for name, entry in self._modules.items()
            if entry.get("status") == "pending"
        ]

    def mark_active(self, module_name: str) -> None:
        """Mark a previously pending module as active."""
        if module_name not in self._modules:
            logger.warning(
                f"ModuleRegistry: mark_active called for unknown module '{module_name}'"
            )
            return
        self._modules[module_name]["status"] = "active"
        logger.info(f"ModuleRegistry: '{module_name}' marked active")


# Module-level singleton used by all modules in the same process.
registry = ModuleRegistry()
