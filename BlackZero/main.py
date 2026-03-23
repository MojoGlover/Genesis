#!/usr/bin/env python3
"""
main.py — Agent entry point.

Stamped from BlackZero at creation. This file belongs to {AGENT_NAME}.

Usage:
    python main.py                          # interactive mode
    python main.py --once "do this thing"   # single cycle and exit
    python main.py --health                 # run health check and exit
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Works both when run directly (stamped agent) and from GENESIS (BlackZero itself)
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))          # stamped agent: agent root on path
sys.path.insert(0, str(_here.parent))   # BlackZero in GENESIS: GENESIS/ on path

try:
    from loader import boot             # stamped agent
except ImportError:
    from BlackZero.loader import boot   # running directly from GENESIS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def run_health_check(loop) -> int:
    """Run the built-in health check and print a structured report."""
    try:
        from diagnostics.agent_health import AgentHealthCheck
        executor = loop._executor
        hc = AgentHealthCheck(
            model_router=getattr(executor, "_model_router", None),
            memory_manager=getattr(executor, "_memory_manager", None),
            tool_registry=getattr(executor, "_tool_registry", None),
        )
        report = hc.check_all()
        status = report["overall"]
        print(f"\nHealth: {status}\n")
        for sub in report["subsystems"]:
            icon = "✓" if sub["status"] == "HEALTHY" else ("~" if sub["status"] == "DEGRADED" else "✗")
            msg  = f"  {icon} {sub['name']}: {sub['status']}"
            if sub["message"]:
                msg += f" — {sub['message']}"
            print(msg)
        print()
        return 0 if status == "HEALTHY" else 1
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent cognitive loop")
    parser.add_argument("--once", nargs="+", metavar="PROMPT",
                        help="Run one cognitive cycle with the given prompt and exit")
    parser.add_argument("--health", action="store_true",
                        help="Run health check and exit")
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml (default: config.yaml)")
    args = parser.parse_args()

    config_path = str(_here / args.config)
    modules_dir = str(_here / "modules")

    loop = boot(config_path, modules_dir)

    if args.health:
        sys.exit(run_health_check(loop))

    if args.once:
        prompt = " ".join(args.once)
        result = loop.run_once(prompt)
        print(f"\n[cycle {result['cycle_id']}] {result['outcome']} "
              f"(score={result['score']:.2f}, {result['duration_ms']:.0f}ms)")
        return

    # Default: interactive loop
    from config_loader import AgentConfig
    cfg  = AgentConfig(_here / args.config)
    name = cfg.designation or "Agent"
    print(f"\n{name} online. Type to interact. Ctrl+C to stop.\n")
    loop.run()


if __name__ == "__main__":
    main()
