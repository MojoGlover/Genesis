"""
realizer.py — Self-Realization Engine

Adds the self-improvement module to a forged agent, making it "self-realized."

A self-realized agent has its own internal improvement loop that:
- Introspects on recent cycle performance
- Benchmarks against its own test suite
- Proposes config mutations (strategy weights, model params, routing)
- Tests mutations in sandbox
- Accepts improvements, rejects regressions
- Journals everything

A non-realized agent depends on Botico to run those routines externally.
That costs a tax.

Implementation:
    1. Copies self_improvement/ template into agent's modules/
    2. Adds self_improvement config to agent's config.yaml
    3. Creates data/ directory for journal + benchmark results
    4. Updates .build_manifest.json
    5. Does NOT modify brain/ or policies/ (genesis_rules.md: BRAIN RULE)

The self_improvement module hooks into BlackZero via the `input_feed` slot
(loader.py line 46: _LIST_SLOTS = {"tools", "input_feed"}).

Usage:
    from builders.realizer import Realizer

    realizer = Realizer()
    realizer.realize("/path/to/agent")
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Template location
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "self_improvement"


class RealizationError(Exception):
    pass


class Realizer:
    """Adds self-improvement capabilities to a forged agent."""

    def realize(
        self,
        agent_dir: str | Path,
        cadence_cycles: int = 50,
        enabled: bool = True,
    ) -> Path:
        """
        Make an agent self-realized by wiring in the improvement module.

        Args:
            agent_dir: Path to the forged agent directory
            cadence_cycles: How often (in cognitive cycles) to run improvement
            enabled: Whether improvement starts enabled (can be toggled later)

        Returns:
            Path to the installed self_improvement module

        Raises:
            RealizationError: If the agent can't be realized
        """
        agent_dir = Path(agent_dir).resolve()

        # Validate
        self._validate(agent_dir)

        # 1. Copy template into agent's modules/
        modules_dir = agent_dir / "modules"
        modules_dir.mkdir(exist_ok=True)
        target_dir = modules_dir / "self_improvement"

        if target_dir.exists():
            raise RealizationError(
                f"Agent already has self_improvement module at {target_dir}"
            )

        if not _TEMPLATE_DIR.exists():
            raise RealizationError(
                f"Self-improvement template not found at {_TEMPLATE_DIR}"
            )

        shutil.copytree(_TEMPLATE_DIR, target_dir)
        logger.info(f"Installed self_improvement module at {target_dir}")

        # 2. Update config.yaml with self_improvement settings
        self._update_config(agent_dir, cadence_cycles, enabled)

        # 3. Create data directory for journal + benchmarks
        data_dir = agent_dir / "data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "benchmark_results").mkdir(exist_ok=True)

        # 4. Update build manifest
        self._update_manifest(agent_dir)

        logger.info(
            f"Agent at {agent_dir} is now self-realized. "
            f"Cadence: {cadence_cycles} cycles. Enabled: {enabled}."
        )

        return target_dir

    def unrealize(self, agent_dir: str | Path) -> None:
        """
        Disable self-realization without removing the module.

        Sets self_improvement.enabled = false in config.
        The module stays installed but the loop won't fire.
        """
        agent_dir = Path(agent_dir).resolve()
        self._update_config(agent_dir, enabled=False)
        logger.info(f"Self-improvement disabled for agent at {agent_dir}")

    def is_realized(self, agent_dir: str | Path) -> bool:
        """Check if an agent has the self-improvement module installed."""
        agent_dir = Path(agent_dir).resolve()
        module_dir = agent_dir / "modules" / "self_improvement"
        if not module_dir.exists():
            return False

        # Check config
        config = self._read_config(agent_dir)
        si_config = config.get("self_improvement", {})
        return si_config.get("enabled", False)

    # ── Validation ─────────────────────────────────────────────────────────────

    def _validate(self, agent_dir: Path) -> None:
        """Ensure the agent is eligible for self-realization."""
        if not agent_dir.exists():
            raise RealizationError(f"Agent directory not found: {agent_dir}")

        # Must have brain/ (proves it was forged from BlackZero)
        if not (agent_dir / "brain").exists():
            raise RealizationError(
                "No brain/ directory — agent may not be forged from BlackZero."
            )

        # Must have config.yaml
        if not (agent_dir / "config.yaml").exists():
            raise RealizationError("No config.yaml — agent not properly forged.")

        # Must not already be Botico-exported
        if (agent_dir / ".botico_exported").exists():
            raise RealizationError(
                "Agent already exported to Botico — cannot modify."
            )

        # Must have tests/ for benchmarking to be meaningful
        if not (agent_dir / "tests").exists():
            logger.warning(
                "Agent has no tests/ directory. Benchmarks will return neutral scores."
            )

    # ── Config Management ──────────────────────────────────────────────────────

    def _read_config(self, agent_dir: Path) -> dict:
        """Read agent's config.yaml."""
        config_path = agent_dir / "config.yaml"
        if not config_path.exists():
            return {}
        try:
            import yaml
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _update_config(
        self,
        agent_dir: Path,
        cadence_cycles: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        """Add or update self_improvement section in config.yaml."""
        import yaml

        config_path = agent_dir / "config.yaml"
        config = self._read_config(agent_dir)

        si_config = config.get("self_improvement", {})

        if cadence_cycles is not None:
            si_config["cadence_cycles"] = cadence_cycles
        if enabled is not None:
            si_config["enabled"] = enabled

        si_config.setdefault("cadence_cycles", 50)
        si_config.setdefault("enabled", True)

        config["self_improvement"] = si_config

        # Also ensure agent_dir is set so the module can find itself
        config["agent_dir"] = str(agent_dir)

        with open(config_path, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False)

        logger.debug(f"Updated config.yaml with self_improvement: {si_config}")

    # ── Manifest Update ────────────────────────────────────────────────────────

    def _update_manifest(self, agent_dir: Path) -> None:
        """Update .build_manifest.json to record self-realization."""
        manifest_path = agent_dir / ".build_manifest.json"

        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except Exception:
                manifest = {}
        else:
            manifest = {}

        manifest["self_realized"] = True
        manifest["self_realized_at"] = datetime.now(timezone.utc).isoformat()
        manifest["self_improvement_config"] = {
            "module_path": "modules/self_improvement",
            "hook": "input_feed",
            "constraints": [
                "never modifies brain/",
                "never modifies policies/",
                "never modifies own code",
                "all mutations logged to improvement_journal.jsonl",
                "operator can disable via config",
            ],
        }

        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        logger.debug("Updated .build_manifest.json with self-realization record")
