"""
watchdog — ADB logcat crash monitor and auto-restart for Computer Black.

Tails adb logcat for MadJanet crashes, surfaces errors in the terminal,
and optionally auto-restarts the app when it dies.

Quick start:
    cd /Users/darnieglover/ai/GENESIS
    python -m watchdog --help
    python -m watchdog                     # watch MadJanet (default)
    python -m watchdog --project madjanet --auto-restart
    python -m watchdog --tail-lines 200    # show last 200 lines first
    python -m watchdog --filter ERROR      # only show errors
"""
from .monitor import WatchdogMonitor, tail_logs, watch
from .config import WATCHDOG_CONFIG

__all__ = ["WatchdogMonitor", "tail_logs", "watch", "WATCHDOG_CONFIG"]
