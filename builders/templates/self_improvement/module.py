"""
self_improvement module — BlackZero module interface.

Hooks into the cognitive loop via the `input_feed` slot.
The improvement loop runs on a configurable cadence alongside the main loop,
never blocking it.

Module contract:
    def setup(config: dict) -> dict
    Returns: {"input_feed": attach_improvement_feed}
"""

from __future__ import annotations

import logging
from pathlib import Path

from .improvement_loop import ImprovementLoop

logger = logging.getLogger(__name__)


def setup(config: dict) -> dict:
    """
    Called by BlackZero loader during boot.

    Returns a dict with an input_feed callable that the loader
    will invoke post-wire with the router reference.
    """
    agent_dir = Path(config.get("agent_dir", ".")).resolve()
    self_improvement_config = config.get("self_improvement", {})

    # Build the improvement loop
    loop = ImprovementLoop(
        agent_dir=agent_dir,
        cadence_cycles=self_improvement_config.get("cadence_cycles", 50),
        enabled=self_improvement_config.get("enabled", True),
    )

    def attach_improvement_feed(router):
        """
        Called post-wire by the loader. Registers the improvement loop
        as an observer that fires every N cycles.
        """
        if not loop.enabled:
            logger.info("Self-improvement disabled in config. Skipping.")
            return

        # Register a sink that the improvement loop uses to observe cycle outcomes
        router.register_sink("self_improvement", loop.observe_cycle)
        logger.info(
            f"Self-improvement wired. Cadence: every {loop.cadence_cycles} cycles."
        )

    return {"input_feed": attach_improvement_feed}
