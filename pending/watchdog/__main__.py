"""
watchdog/__main__.py — ADB log monitor CLI.

Usage:
    python -m watchdog                             # watch MadJanet
    python -m watchdog --auto-restart              # auto-restart on crash
    python -m watchdog --filter ERROR              # only show errors
    python -m watchdog --tail 100                  # show last 100 lines and exit
    python -m watchdog --project madjanet
"""
from __future__ import annotations
import argparse

from .config import WATCHDOG_CONFIG
from .monitor import tail_logs, watch


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="watchdog",
        description="Computer Black — ADB logcat crash monitor",
    )
    p.add_argument("--project", "-p", default="madjanet",
                   choices=list(WATCHDOG_CONFIG.keys()),
                   help="Project to monitor (default: madjanet)")
    p.add_argument("--auto-restart", "-r", action="store_true",
                   help="Auto-restart app on crash")
    p.add_argument("--filter", "-f", default=None, metavar="LEVEL",
                   help="Filter by log level: ERROR, WARN, INFO, DEBUG")
    p.add_argument("--tail", "-t", type=int, default=None, metavar="N",
                   help="Show last N lines and exit (no live stream)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print(f"\n  Computer Black — Watchdog [{args.project}]")

    if args.tail is not None:
        tail_logs(project_key=args.project, lines=args.tail, level_filter=args.filter)
    else:
        watch(project_key=args.project, auto_restart=args.auto_restart, level_filter=args.filter)


if __name__ == "__main__":
    main()
