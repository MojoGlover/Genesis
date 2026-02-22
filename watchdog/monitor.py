"""watchdog/monitor.py — ADB logcat crash monitor."""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
import time
from typing import Optional

from .config import WATCHDOG_CONFIG, DEFAULT_TAIL_LINES, COLORS


def _adb_ok() -> bool:
    return bool(shutil.which("adb"))


def _colorize(line: str, project_cfg: dict) -> str:
    C = COLORS
    for pattern in project_cfg.get("crash_patterns", []):
        if re.search(pattern, line, re.IGNORECASE):
            return f"{C['crash']}{line}{C['reset']}"
    if "ERROR" in line or "E/" in line:
        return f"{C['error']}{line}{C['reset']}"
    if "WARN" in line or "W/" in line:
        return f"{C['warn']}{line}{C['reset']}"
    return f"{C['gray']}{line}{C['reset']}"


def _should_show(line: str, project_cfg: dict, level_filter: Optional[str]) -> bool:
    # Drop ignored patterns
    for pat in project_cfg.get("ignore_patterns", []):
        if re.search(pat, line):
            return False
    # Tag filter: only show lines from relevant tags
    tags = project_cfg.get("tag_filter", [])
    if tags and not any(tag in line for tag in tags):
        # Still show crashes and errors regardless of tag
        if not any(re.search(p, line, re.IGNORECASE)
                   for p in project_cfg.get("crash_patterns", [])):
            return False
    # Level filter
    if level_filter and level_filter.upper() not in line:
        return False
    return True


def _get_device_serial() -> Optional[str]:
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return None


def tail_logs(project_key: str = "madjanet",
              lines: int = DEFAULT_TAIL_LINES,
              level_filter: Optional[str] = None) -> None:
    """Print the last N log lines and return."""
    if not _adb_ok():
        print("  ✗ adb not found")
        sys.exit(1)

    cfg = WATCHDOG_CONFIG.get(project_key, {})
    serial = _get_device_serial()
    if not serial:
        print("  ✗ No device connected")
        sys.exit(1)

    result = subprocess.run(
        ["adb", "-s", serial, "logcat", "-d", "-t", str(lines)],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if _should_show(line, cfg, level_filter):
            print(_colorize(line, cfg))


class WatchdogMonitor:
    def __init__(self, project_key: str = "madjanet",
                 auto_restart: bool = False,
                 level_filter: Optional[str] = None):
        self.project_key   = project_key
        self.cfg           = WATCHDOG_CONFIG.get(project_key, {})
        self.auto_restart  = auto_restart
        self.level_filter  = level_filter
        self.package       = self.cfg.get("package", "")
        self._running      = False

    def _restart_app(self, serial: str) -> None:
        activity = f"{self.package}/.MainActivity"
        print(f"\n{COLORS['green']}  → Auto-restarting {self.package}...{COLORS['reset']}")
        subprocess.run(
            ["adb", "-s", serial, "shell", "am", "start", "-n", activity],
            capture_output=True
        )

    def start(self) -> None:
        if not _adb_ok():
            print("  ✗ adb not found")
            sys.exit(1)

        serial = _get_device_serial()
        if not serial:
            print("  ✗ No device connected")
            sys.exit(1)

        C = COLORS
        print(f"\n  {C['green']}Watching {self.project_key} on {serial}{C['reset']}")
        print(f"  Auto-restart: {'ON' if self.auto_restart else 'OFF'}")
        print(f"  Press Ctrl+C to stop.\n")

        # Clear logcat first
        subprocess.run(["adb", "-s", serial, "logcat", "-c"], capture_output=True)

        proc = subprocess.Popen(
            ["adb", "-s", serial, "logcat"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )

        self._running = True
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not _should_show(line, self.cfg, self.level_filter):
                    continue

                colored = _colorize(line, self.cfg)
                print(colored)

                # Detect crash
                if self.auto_restart and any(
                    re.search(p, line, re.IGNORECASE)
                    for p in self.cfg.get("crash_patterns", [])
                ):
                    time.sleep(1)
                    self._restart_app(serial)

        except KeyboardInterrupt:
            pass
        finally:
            proc.terminate()
            print(f"\n  {C['gray']}Watchdog stopped.{C['reset']}\n")


def watch(project_key: str = "madjanet",
          auto_restart: bool = False,
          level_filter: Optional[str] = None) -> None:
    WatchdogMonitor(project_key, auto_restart, level_filter).start()
