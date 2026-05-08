"""
python_repl.py — Execute Python code in a subprocess sandbox.

Runs code in an isolated subprocess with timeout.
stdout/stderr captured and returned.
No persistent state between calls — each run is fresh.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


def run(code: str, cwd: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Execute Python code string. Returns stdout, stderr, returncode.
    Code runs in a subprocess — no access to agent internals.
    """
    working_dir = Path(cwd).expanduser() if cwd else Path.cwd()

    logger.info(f"[python_repl] Executing {len(code)} chars of Python")

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timed out after {timeout}s", "returncode": -1, "error": "timeout"}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "error": str(e)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def format_result(result: dict) -> str:
    parts = []
    if result["stdout"].strip():
        parts.append(f"stdout:\n{result['stdout'].strip()}")
    if result["stderr"].strip():
        parts.append(f"stderr:\n{result['stderr'].strip()}")
    parts.append(f"exit: {result['returncode']}")
    if result.get("error"):
        parts.append(f"error: {result['error']}")
    return "\n".join(parts) if parts else "(no output)"
