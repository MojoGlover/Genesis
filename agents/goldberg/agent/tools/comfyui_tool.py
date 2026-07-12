"""
comfyui_tool.py — ComfyUI runtime integration for Goldberg.

Four actions:
  queue_status()               — how many jobs are running / pending
  poll_result(prompt_id)       — wait until a job finishes, return output paths
  view_output(prompt_id)       — open the output image(s) in macOS Preview
  list_outputs(n)              — list recent output files with paths + URLs
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_COMFYUI_BASE   = "http://127.0.0.1:8188"
_OUTPUT_DIR     = Path(os.path.expanduser("~/ai/cmptrblk/art/ComfyUI/output"))
_TIMEOUT        = httpx.Timeout(10.0)
_POLL_INTERVAL  = 2.0    # seconds between history checks
_POLL_MAX       = 180    # give up after 3 minutes


def _comfyui_up() -> bool:
    try:
        httpx.get(f"{_COMFYUI_BASE}/system_stats", timeout=3.0)
        return True
    except Exception:
        return False


def _history(prompt_id: str) -> dict | None:
    """Return the history entry for a prompt_id, or None if not done yet."""
    try:
        r = httpx.get(f"{_COMFYUI_BASE}/history/{prompt_id}", timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            return data.get(prompt_id)
        return None
    except Exception:
        return None


def _extract_images(history_entry: dict) -> list[dict]:
    """Pull image records out of a ComfyUI history entry."""
    images = []
    for node_id, node_output in history_entry.get("outputs", {}).items():
        for img in node_output.get("images", []):
            fname     = img.get("filename", "")
            subfolder = img.get("subfolder", "")
            itype     = img.get("type", "output")
            if fname:
                rel_path  = Path(subfolder) / fname if subfolder else Path(fname)
                full_path = _OUTPUT_DIR / rel_path
                view_url  = (
                    f"{_COMFYUI_BASE}/view"
                    f"?filename={fname}&subfolder={subfolder}&type={itype}"
                )
                images.append({
                    "filename":  fname,
                    "path":      str(full_path),
                    "view_url":  view_url,
                    "exists":    full_path.exists(),
                })
    return images


# ── Public tool functions ─────────────────────────────────────────────────────

def queue_status() -> dict:
    """
    Return the current ComfyUI queue depth.

    Returns:
        {"ok": True, "running": N, "pending": N}
    """
    if not _comfyui_up():
        return {"ok": False, "error": "ComfyUI not running at 127.0.0.1:8188"}
    try:
        r = httpx.get(f"{_COMFYUI_BASE}/queue", timeout=_TIMEOUT)
        data = r.json()
        return {
            "ok":      True,
            "running": len(data.get("queue_running", [])),
            "pending": len(data.get("queue_pending", [])),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def poll_result(prompt_id: str, timeout: int = _POLL_MAX) -> dict:
    """
    Block until a queued prompt finishes, then return output image paths.

    Args:
        prompt_id: from civitai_deploy_workflow or any ComfyUI /api/prompt call
        timeout:   max seconds to wait (default 180)

    Returns:
        {"ok": True, "images": [{"filename", "path", "view_url", "exists"}]}
    """
    if not _comfyui_up():
        return {"ok": False, "error": "ComfyUI not running"}

    deadline = time.time() + timeout
    while time.time() < deadline:
        entry = _history(prompt_id)
        if entry:
            images = _extract_images(entry)
            return {"ok": True, "prompt_id": prompt_id, "images": images}
        time.sleep(_POLL_INTERVAL)

    return {"ok": False, "error": f"Timed out after {timeout}s — prompt {prompt_id} not complete"}


def view_output(prompt_id: str = "", path: str = "") -> dict:
    """
    Open output image(s) in macOS Preview (or default image viewer).

    Args:
        prompt_id: open all images from this prompt (fetches from history)
        path:      open a specific file path directly (alternative to prompt_id)

    Returns:
        {"ok": True, "opened": ["/abs/path/to/image.png", ...]}
    """
    to_open: list[str] = []

    if path:
        to_open.append(path)
    elif prompt_id:
        entry = _history(prompt_id)
        if not entry:
            return {"ok": False, "error": f"No history entry for prompt {prompt_id} — may still be queued"}
        images = _extract_images(entry)
        to_open = [img["path"] for img in images if img.get("exists")]
        if not to_open:
            # Fall back to view URL if file not local
            urls = [img["view_url"] for img in images]
            if urls:
                for url in urls:
                    subprocess.Popen(["open", url])
                return {"ok": True, "opened": urls, "note": "Opened via browser (file not local)"}
            return {"ok": False, "error": "No output images found in history"}
    else:
        # No args — open the most recent output file
        files = sorted(_OUTPUT_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            files = sorted(_OUTPUT_DIR.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            to_open.append(str(files[0]))
        else:
            return {"ok": False, "error": f"No output images found in {_OUTPUT_DIR}"}

    opened = []
    for p in to_open:
        if os.path.exists(p):
            subprocess.Popen(["open", p])
            opened.append(p)
            logger.info("[comfyui] Opened: %s", p)
        else:
            logger.warning("[comfyui] File not found: %s", p)

    if not opened:
        return {"ok": False, "error": "Files not found on disk — may still be generating"}
    return {"ok": True, "opened": opened}


def list_outputs(n: int = 10) -> dict:
    """
    List the most recent output images with their file paths and ComfyUI view URLs.

    Args:
        n: how many recent files to return (default 10)

    Returns:
        {"ok": True, "images": [{"filename", "path", "view_url", "size_kb", "modified"}]}
    """
    if not _OUTPUT_DIR.exists():
        return {"ok": False, "error": f"Output directory not found: {_OUTPUT_DIR}"}

    files = sorted(
        [f for f in _OUTPUT_DIR.iterdir()
         if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and not f.name.startswith(".")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:n]

    if not files:
        return {"ok": True, "images": [], "note": "No output images yet"}

    images = []
    for f in files:
        stat = f.stat()
        view_url = f"{_COMFYUI_BASE}/view?filename={f.name}&subfolder=&type=output"
        images.append({
            "filename": f.name,
            "path":     str(f),
            "view_url": view_url,
            "size_kb":  round(stat.st_size / 1024, 1),
            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
        })

    return {"ok": True, "images": images}
