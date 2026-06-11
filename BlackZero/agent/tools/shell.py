"""
shell.py — Safe shell execution.

Runs commands in a subprocess with timeout and output capture.
Destructive operations require an explicit confirm_destructive flag.
Working directory defaults to the agent's own directory (no hardcoded paths).
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

_DESTRUCTIVE_PATTERNS = [
    "rm -rf", "rm -r", "rmdir",
    "git push --force", "git push -f",
    "git reset --hard", "git clean -f",
    "drop table", "drop database",
    "mkfs", "dd if=",
    ":(){:|:&};:",
    # Command substitution — blocks injection via $(cmd) and `cmd`
    "$(", "`",
]

# Environment variables stripped from shell subprocesses — credentials and
# secrets that shell commands shouldn't need but that would otherwise be
# readable via `env`, error messages, or a malicious/compromised command.
_SENSITIVE_ENV_PREFIXES = (
    "ANTHROPIC_", "OPENAI_", "GOOGLE_", "GEMINI_", "GCP_",
    "AWS_", "REPLICATE_", "ELEVENLABS_", "CIVITAI_",
    "GH_TOKEN", "GITHUB_TOKEN", "NPM_TOKEN",
)
_SENSITIVE_ENV_EXACT = ("SSH_AUTH_SOCK",)


def _scrubbed_env() -> dict:
    """Subprocess environment with API keys, cloud credentials, and the
    SSH agent socket removed."""
    return {
        k: v for k, v in os.environ.items()
        if k not in _SENSITIVE_ENV_EXACT
        and not any(k.startswith(p) for p in _SENSITIVE_ENV_PREFIXES)
    }


# Default cwd: agent's root directory (set at boot, configurable via env)
DEFAULT_CWD = os.environ.get("AGENT_WORK_DIR", str(Path(__file__).parents[3]))


def run(command: str, cwd: str = "", timeout: int = 60,
        confirm_destructive: bool = False) -> dict:
    """
    Execute a shell command. Returns dict with stdout, stderr, returncode.
    """
    effective_cwd = cwd or DEFAULT_CWD

    cmd_lower = command.lower()
    for pattern in _DESTRUCTIVE_PATTERNS:
        if pattern in cmd_lower:
            if not confirm_destructive:
                return {
                    "stdout": "",
                    "stderr": f"Blocked: '{pattern}' requires confirm_destructive=true",
                    "returncode": 1,
                    "blocked": True,
                }

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=effective_cwd,
            env=_scrubbed_env(),
        )
        return {
            "stdout":     result.stdout,
            "stderr":     result.stderr,
            "returncode": result.returncode,
            "blocked":    False,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timed out after {timeout}s", "returncode": 1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": 1}


def format_result(result: dict) -> str:
    parts = []
    if result.get("blocked"):
        return f"BLOCKED: {result['stderr']}"
    if result["stdout"].strip():
        parts.append(result["stdout"].strip())
    if result["stderr"].strip():
        parts.append(f"[stderr]: {result['stderr'].strip()}")
    parts.append(f"[exit {result['returncode']}]")
    return "\n".join(parts) if parts else f"[exit {result['returncode']}]"
