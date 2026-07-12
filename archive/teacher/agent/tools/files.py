"""
files.py — File system tools for Engineer0.

Read, write, list, search, and patch files.
All writes are logged. No silent overwrites.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_READ_BYTES = 100_000  # 100KB — prevent context explosion


def read(path: str, offset: int = 0, limit: int = 200) -> dict:
    """Read a file. Returns content with line numbers."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"File not found: {path}", "content": ""}
    if not p.is_file():
        return {"error": f"Not a file: {path}", "content": ""}

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        sliced = lines[offset:offset + limit]
        numbered = "\n".join(f"{offset + i + 1}\t{line}" for i, line in enumerate(sliced))
        return {
            "path": str(p),
            "content": numbered,
            "total_lines": total,
            "shown": f"{offset + 1}-{offset + len(sliced)}",
            "error": None,
        }
    except Exception as e:
        return {"error": str(e), "content": ""}


def write(path: str, content: str, overwrite: bool = True) -> dict:
    """Write content to a file. Creates parent dirs if needed."""
    p = Path(path).expanduser()
    if p.exists() and not overwrite:
        return {"error": f"File exists and overwrite=False: {path}", "written": False}

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        logger.info(f"[files] Written {len(content)} chars to {path}")
        return {"path": str(p), "bytes": len(content.encode()), "written": True, "error": None}
    except Exception as e:
        logger.error(f"[files] Write failed: {e}")
        return {"error": str(e), "written": False}


def append(path: str, content: str) -> dict:
    """Append content to a file."""
    p = Path(path).expanduser()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[files] Appended {len(content)} chars to {path}")
        return {"path": str(p), "bytes": len(content.encode()), "written": True, "error": None}
    except Exception as e:
        return {"error": str(e), "written": False}


def patch(path: str, old_string: str, new_string: str) -> dict:
    """Replace exact string in a file. Fails if old_string not found."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"File not found: {path}", "patched": False}

    try:
        text = p.read_text(encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            return {"error": f"String not found in {path}", "patched": False}
        if count > 1:
            return {"error": f"String found {count} times — too ambiguous. Add more context.", "patched": False}

        new_text = text.replace(old_string, new_string, 1)
        p.write_text(new_text, encoding="utf-8")
        logger.info(f"[files] Patched {path}")
        return {"path": str(p), "patched": True, "error": None}
    except Exception as e:
        return {"error": str(e), "patched": False}


def list_dir(path: str = ".", pattern: str = "*", recursive: bool = False) -> dict:
    """List files in a directory."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"Path not found: {path}", "files": []}

    try:
        if recursive:
            files = [str(f.relative_to(p)) for f in p.rglob(pattern) if f.is_file()]
        else:
            files = [f.name for f in p.glob(pattern)]
        files.sort()
        return {"path": str(p), "files": files[:500], "count": len(files), "error": None}
    except Exception as e:
        return {"error": str(e), "files": []}


def search(path: str, pattern: str, file_glob: str = "*.py") -> dict:
    """Search for a pattern in files. Returns matching lines with file:line."""
    import re
    root = Path(path).expanduser()
    results = []

    try:
        regex = re.compile(pattern, re.IGNORECASE)
        for f in root.rglob(file_glob):
            if ".git" in f.parts:
                continue
            try:
                for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{f}:{i}: {line.strip()}")
                        if len(results) >= 200:
                            break
            except Exception:
                continue

        return {"pattern": pattern, "matches": results, "count": len(results), "error": None}
    except re.error as e:
        return {"error": f"Invalid regex: {e}", "matches": []}
