"""
units.py — generate the OS timer that fires a duty.

Timers live in the OS, not in the agent process. An agent that must be running
to notice it is unhealthy is not a monitor — if it crashes, its own health
checks die with it, and the last thing it recorded was "healthy". Putting the
trigger in systemd/launchd means the evidence keeps arriving (or visibly stops)
regardless of the agent's state.

Generates text only; installing is the caller's job (build_agent.py at stamp
time), so nothing here needs root or touches a live system.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["systemd_units", "launchd_plist", "duty_command"]


def duty_command(agent_root: Path, duty_name: str, python: str | None = None) -> str:
    """The command a timer runs. Deliberately one entry point for every duty —
    a per-duty script is how you end up with five that drifted apart.

    `agent.duties.cli`, not `modules.duties.cli`: in a stamped agent the package
    lives under agent/ (agents never import GENESIS at runtime). Getting this
    wrong produces timers that look correct and fail on every single fire.
    """
    py = python or f"{agent_root}/.venv/bin/python"
    return f"{py} -m agent.duties.cli --duty {duty_name}"


def systemd_units(agent_id: str, agent_root: Path, duty_name: str,
                  every_seconds: int, description: str = "") -> tuple[str, str]:
    """Returns (service_text, timer_text) for one duty."""
    unit = f"{agent_id}-{duty_name}"
    desc = description or f"{agent_id} duty: {duty_name}"

    service = f"""[Unit]
Description={desc} (deterministic — no model in the trigger path)
Documentation=file://{agent_root}/modules/duties/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={agent_root}
ExecStart={duty_command(agent_root, duty_name)}
User=root
"""

    timer = f"""[Unit]
Description=Run {desc} every {every_seconds}s

[Timer]
OnBootSec=5min
OnUnitActiveSec={every_seconds}s
AccuracySec=1min
RandomizedDelaySec={min(600, max(30, every_seconds // 20))}s
# Persistent so a duty missed while the box was down runs on next boot —
# a monitoring gap should not be silently skipped.
Persistent=true

[Install]
WantedBy=timers.target
"""
    return service, timer


def launchd_plist(agent_id: str, agent_root: Path, duty_name: str,
                  every_seconds: int) -> str:
    """macOS equivalent, for agents running on plugwan."""
    label = f"com.cmptrblk.{agent_id}.{duty_name}"
    cmd = duty_command(agent_root, duty_name).split()
    args = "\n".join(f"        <string>{c}</string>" for c in cmd)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>WorkingDirectory</key><string>{agent_root}</string>
    <key>StartInterval</key><integer>{every_seconds}</integer>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>/tmp/{label}.log</string>
    <key>StandardErrorPath</key><string>/tmp/{label}.err</string>
</dict>
</plist>
"""
