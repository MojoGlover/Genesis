"""
config_loader.py — Typed config access for agents.

Stamped from BlackZero at creation. Rename class to {AGENT_NAME}Config
and add agent-specific properties below.

Usage:
    from config_loader import AgentConfig
    cfg = AgentConfig("config.yaml")
    print(cfg.designation)      # "Engineer0"
    print(cfg.data_dir)         # Path("~/.engineer0").expanduser()
    print(cfg.reasoning_model)  # "engineer0:latest"
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class AgentConfig:
    """
    Typed, property-based access to config.yaml.

    All raw values are accessible via cfg.raw["key"]["subkey"].
    Typed properties below are the preferred access pattern.

    Rename this class to {AGENT_NAME}Config when stamping.
    """

    def __init__(self, config_path: str | Path) -> None:
        config_path = Path(config_path).resolve()
        with open(config_path) as f:
            self.raw: dict[str, Any] = yaml.safe_load(f) or {}
        self._path = config_path

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def designation(self) -> str:
        return self.raw.get("identity", {}).get("designation", "Agent")

    @property
    def alias(self) -> str:
        return self.raw.get("identity", {}).get("alias", self.designation)

    @property
    def role(self) -> str:
        return self.raw.get("identity", {}).get("role", "")

    @property
    def pronouns(self) -> str:
        return self.raw.get("identity", {}).get("pronouns", "they/them")

    # ── Storage ───────────────────────────────────────────────────────────────

    @property
    def data_dir(self) -> Path:
        import os
        raw = os.environ.get("DATA_DIR") or self.raw.get("data_dir", "~/.agent")
        return Path(raw).expanduser()

    # ── Models ────────────────────────────────────────────────────────────────

    @property
    def reasoning_model(self) -> str:
        return self.raw.get("models", {}).get("reasoning", "mistral:latest")

    @property
    def code_model(self) -> str:
        return self.raw.get("models", {}).get("code", "qwen2.5-coder:7b")

    # ── Tools ─────────────────────────────────────────────────────────────────

    @property
    def ollama_api_url(self) -> str:
        import os
        return (
            os.environ.get("OLLAMA_API_URL")
            or self.raw.get("tools", {}).get("ollama_api", "http://localhost:11434/api")
        )

    # ── Loop ──────────────────────────────────────────────────────────────────

    @property
    def check_interval(self) -> int:
        return self.raw.get("loop", {}).get("check_interval_seconds", 30)

    @property
    def task_timeout(self) -> int:
        return self.raw.get("loop", {}).get("task_timeout_seconds", 300)

    # ── Modules ───────────────────────────────────────────────────────────────

    def module_config(self, module_name: str) -> dict:
        return self.raw.get("modules", {}).get(module_name, {})

    # ── Raw access ────────────────────────────────────────────────────────────

    def get(self, *keys: str, default: Any = None) -> Any:
        """Dot-path accessor: cfg.get("loop", "max_retries", default=3)"""
        node = self.raw
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key, default)
        return node

    def __repr__(self) -> str:
        return f"AgentConfig({self.designation!r}, path={self._path})"
