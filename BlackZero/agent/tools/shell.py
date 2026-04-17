"""
shell.py — Safe shell execution for Engineer0.

Runs commands in a subprocess with timeout and output capture.
Destructive operations require confirmation flag.
All commands are logged.
"""
from __future__ import annotations

import logging
import subprocess
import shlex
from pathlib import Path

logger = logging.getLogger(__name__)

# Commands that are destructive and should be flagged
_DESTRUCTIVE_PATTERNS = [
    "rm -rf", "rm -r", "git push --force", "git push -f",
    "git reset --hard", "git clean -f", "drop table", "truncate",
    "mkfs", "dd if=", "chmod -R 777",
]

DEFAULT_TIMEOUT = 60  # seconds


def run(
    command: str,
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    confirm_destructive: bool = False,
) -> dict:
    """
    Run a shell command. Returns dict with stdout, stderr, returncode, error.

    Args:
        command: Shell command string
        cwd: Working directory (defaults to cmptrblk root)
        timeout: Seconds before killing process
        confirm_destructive: Must be True to run destructive commands
    """
    # Check for destructive patterns
    cmd_lower = command.lower()
    for pattern in _DESTRUCTIVE_PATTERNS:
        if pattern in cmd_lower:
            if not confirm_destructive:
                logger.warning(f"[shell] Destructive command blocked: {command}")
                return {
                    "stdout": "",
                    "stderr": f"BLOCKED: '{pattern}' is a destructive operation. "
                              "Set confirm_destructive=True to proceed.",
                    "returncode": -1,
                    "error": "destructive_blocked",
                    "command": command,
                }

    working_dir = Path(cwd).expanduser() if cwd else Path("/Users/darnieglover/ai/cmptrblk")

    logger.info(f"[shell] $ {command} (cwd={working_dir})")

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(f"[shell] exit {result.returncode}: {result.stderr[:200]}")
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "error": None,
            "command": command,
        }
    except subprocess.TimeoutExpired:
        logger.error(f"[shell] Timeout after {timeout}s: {command}")
        return {"stdout": "", "stderr": f"Timed out after {timeout}s", "returncode": -1, "error": "timeout", "command": command}
    except Exception as e:
        logger.error(f"[shell] Error: {e}")
        return {"stdout": "", "stderr": str(e), "returncode": -1, "error": str(e), "command": command}


def format_result(result: dict) -> str:
    """Format shell result for LLM consumption."""
    parts = [f"$ {result['command']}", f"exit: {result['returncode']}"]
    if result["stdout"].strip():
        parts.append(f"stdout:\n{result['stdout'].strip()}")
    if result["stderr"].strip():
        parts.append(f"stderr:\n{result['stderr'].strip()}")
    if result.get("error"):
        parts.append(f"error: {result['error']}")
    return "\n".join(parts)
