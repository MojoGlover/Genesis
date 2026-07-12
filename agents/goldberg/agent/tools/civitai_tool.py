"""
civitai_tool.py — CivitAI integration for Goldberg.

Five actions:
  list_models(query, type)     — search CivitAI for checkpoints / LoRAs / etc.
  fetch_workflow(url)          — pull workflow JSON from a CivitAI image/model page
  download_model(model_id)     — download a model version into local_models/
  analyze_workflow(workflow)   — list what models/nodes a workflow requires
  deploy_workflow(workflow)    — POST workflow to ComfyUI and return prompt_id

API key: reads config.yaml tools.civitai_api_key or CIVITAI_API_KEY env var.
Public endpoints (list, fetch) work without a key.
Downloads require a key for gated/early-access models.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

_CIVITAI_BASE  = "https://civitai.com/api/v1"
_COMFYUI_BASE  = "http://127.0.0.1:8188"
_TIMEOUT       = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)
_DL_TIMEOUT    = httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=5.0)

# Model type → subdirectory under local_models base
_TYPE_DIR: dict[str, str] = {
    "Checkpoint":        "checkpoints",
    "LORA":              "loras",
    "LoCon":             "loras",
    "TextualInversion":  "embeddings",
    "Controlnet":        "controlnet",
    "VAE":               "vae",
    "Upscaler":          "upscale_models",
    "AestheticGradient": "embeddings",
    "Poses":             "controlnet",
    "Wildcards":         "wildcards",
}

_LOCAL_MODELS_BASE = Path(
    os.path.expanduser("~/ai/cmptrblk/art/local_models")
)


def _api_key() -> str:
    key = os.environ.get("CIVITAI_API_KEY", "")
    if key:
        return key
    cfg_path = Path(__file__).parents[2] / "config.yaml"  # parents[2] = goldberg/
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            return cfg.get("tools", {}).get("civitai_api_key", "")
        except Exception:
            pass
    return ""


def _headers() -> dict:
    key = _api_key()
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


# ── Public tool functions ─────────────────────────────────────────────────────

def list_models(query: str, type: str = "Checkpoint", limit: int = 10) -> dict:
    """
    Search CivitAI for models.

    Args:
        query: search terms (e.g. "realistic portrait")
        type:  Checkpoint | LORA | TextualInversion | Controlnet | VAE | Upscaler
        limit: max results (default 10)

    Returns:
        {"ok": True, "models": [{"id", "name", "type", "downloads", "rating",
                                  "latest_version_id", "preview_url", "tags"}]}
    """
    try:
        r = httpx.get(
            f"{_CIVITAI_BASE}/models",
            params={"query": query, "types": type, "limit": limit, "sort": "Most Downloaded"},
            headers=_headers(),
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}

        data = r.json()
        models = []
        for m in data.get("items", []):
            versions = m.get("modelVersions", [])
            latest = versions[0] if versions else {}
            preview = ""
            for img in latest.get("images", []):
                if img.get("url"):
                    preview = img["url"]
                    break
            models.append({
                "id":                m.get("id"),
                "name":              m.get("name"),
                "type":              m.get("type"),
                "downloads":         m.get("stats", {}).get("downloadCount", 0),
                "rating":            m.get("stats", {}).get("rating", 0),
                "latest_version_id": latest.get("id"),
                "preview_url":       preview,
                "tags":              m.get("tags", [])[:5],
            })
        return {"ok": True, "models": models, "total": data.get("metadata", {}).get("totalItems", len(models))}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def fetch_workflow(url: str) -> dict:
    """
    Fetch a ComfyUI workflow JSON from a CivitAI image or model page URL.

    Args:
        url: CivitAI image URL (https://civitai.com/images/<id>) or
             model version URL (https://civitai.com/models/<id>?modelVersionId=<vid>)

    Returns:
        {"ok": True, "workflow": {...}, "source": "image"|"model_version"}
    """
    try:
        # Extract image ID from URL
        img_match = re.search(r"/images/(\d+)", url)
        mv_match  = re.search(r"modelVersionId=(\d+)", url)
        m_match   = re.search(r"/models/(\d+)", url)

        if img_match:
            image_id = img_match.group(1)
            r = httpx.get(
                f"{_CIVITAI_BASE}/images",
                params={"imageId": image_id},
                headers=_headers(),
                timeout=_TIMEOUT,
                follow_redirects=True,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    meta = items[0].get("meta") or {}
                    if meta:
                        return {"ok": True, "workflow": meta, "source": "image_meta",
                                "note": "Image generation metadata (not a full ComfyUI workflow node graph)"}
            return {"ok": False, "error": f"Image {image_id} not found or no metadata"}

        if mv_match or m_match:
            version_id = mv_match.group(1) if mv_match else None
            if not version_id and m_match:
                # Get latest version from model
                model_id = m_match.group(1)
                r = httpx.get(f"{_CIVITAI_BASE}/models/{model_id}", headers=_headers(),
                               timeout=_TIMEOUT, follow_redirects=True)
                if r.status_code == 200:
                    versions = r.json().get("modelVersions", [])
                    if versions:
                        version_id = versions[0].get("id")

            if version_id:
                r = httpx.get(f"{_CIVITAI_BASE}/model-versions/{version_id}",
                               headers=_headers(), timeout=_TIMEOUT, follow_redirects=True)
                if r.status_code == 200:
                    data = r.json()
                    # Some versions ship workflow files
                    for f in data.get("files", []):
                        if f.get("type") == "Training Data" or "workflow" in f.get("name", "").lower():
                            return {"ok": True, "workflow": f, "source": "model_version_file"}
                    # Return version info as context
                    return {"ok": True, "workflow": {
                        "name":          data.get("name"),
                        "base_model":    data.get("baseModel"),
                        "trained_words": data.get("trainedWords", []),
                        "files":         [{"name": f["name"], "type": f.get("type"), "size_kb": f.get("sizeKB")}
                                          for f in data.get("files", [])],
                    }, "source": "model_version_info",
                    "note": "No embedded workflow found — returned version metadata instead"}

        return {"ok": False, "error": "Could not extract image ID or model version ID from URL"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def download_model(model_version_id: int, dest_name: str = "") -> dict:
    """
    Download a CivitAI model version into the appropriate local_models/ subdirectory.

    Args:
        model_version_id: numeric version ID from list_models() latest_version_id
        dest_name:        optional override filename (default: original filename)

    Returns:
        {"ok": True, "path": "/abs/path/to/model.safetensors", "size_mb": 123}
    """
    try:
        # Get version metadata
        r = httpx.get(
            f"{_CIVITAI_BASE}/model-versions/{model_version_id}",
            headers=_headers(),
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"Version {model_version_id} not found: HTTP {r.status_code}"}

        version = r.json()
        model_type = version.get("model", {}).get("type", "Checkpoint")
        subdir = _TYPE_DIR.get(model_type, "checkpoints")

        # Find the primary file to download
        files = version.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        if not primary:
            return {"ok": False, "error": "No downloadable files in this version"}

        dl_url   = primary.get("downloadUrl") or f"https://civitai.com/api/download/models/{model_version_id}"
        filename = dest_name or primary.get("name", f"civitai_{model_version_id}.safetensors")

        dest_dir = _LOCAL_MODELS_BASE / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        if dest_path.exists():
            size_mb = dest_path.stat().st_size / 1_048_576
            return {"ok": True, "path": str(dest_path), "size_mb": round(size_mb, 1),
                    "note": "Already exists — skipped download"}

        logger.info("[civitai] Downloading %s → %s", filename, dest_path)
        with httpx.stream("GET", dl_url, headers=_headers(), timeout=_DL_TIMEOUT,
                           follow_redirects=True) as resp:
            if resp.status_code != 200:
                return {"ok": False, "error": f"Download failed: HTTP {resp.status_code}"}
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    fh.write(chunk)

        size_mb = dest_path.stat().st_size / 1_048_576
        logger.info("[civitai] Downloaded %s (%.1f MB)", filename, size_mb)
        return {"ok": True, "path": str(dest_path), "size_mb": round(size_mb, 1)}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def analyze_workflow(workflow: dict) -> dict:
    """
    Parse a ComfyUI workflow node graph and list what models/nodes it requires.

    Args:
        workflow: ComfyUI workflow dict (API format: {"1": {"class_type": ...}} or
                  UI format: {"nodes": [...], "links": [...]})

    Returns:
        {"ok": True, "required_models": [...], "node_types": [...], "summary": str}
    """
    try:
        required_models: list[dict] = []
        node_types: set[str] = set()

        # Handle both API format and UI format
        nodes_iter: list[dict] = []

        if "nodes" in workflow:
            # UI format
            nodes_iter = workflow["nodes"]
            for node in nodes_iter:
                node_types.add(node.get("type", "unknown"))
                widgets = node.get("widgets_values", [])
                ntype   = node.get("type", "")
                if "CheckpointLoader" in ntype and widgets:
                    required_models.append({"type": "checkpoint", "name": widgets[0]})
                elif "LoraLoader" in ntype and widgets:
                    required_models.append({"type": "lora", "name": widgets[0]})
                elif "VAELoader" in ntype and widgets:
                    required_models.append({"type": "vae", "name": widgets[0]})
                elif "ControlNetLoader" in ntype and widgets:
                    required_models.append({"type": "controlnet", "name": widgets[0]})
                elif "UNETLoader" in ntype and widgets:
                    required_models.append({"type": "unet", "name": widgets[0]})
                elif "CLIPLoader" in ntype and widgets:
                    required_models.append({"type": "clip", "name": widgets[0]})
        else:
            # API / prompt format: {"node_id": {"class_type": ..., "inputs": {...}}}
            for node_id, node in workflow.items():
                if not isinstance(node, dict):
                    continue
                ctype = node.get("class_type", "")
                node_types.add(ctype)
                inputs = node.get("inputs", {})
                if "CheckpointLoader" in ctype:
                    name = inputs.get("ckpt_name", "")
                    if name:
                        required_models.append({"type": "checkpoint", "name": name})
                elif "LoraLoader" in ctype:
                    name = inputs.get("lora_name", "")
                    if name:
                        required_models.append({"type": "lora", "name": name})
                elif "VAELoader" in ctype:
                    name = inputs.get("vae_name", "")
                    if name:
                        required_models.append({"type": "vae", "name": name})
                elif "ControlNetLoader" in ctype:
                    name = inputs.get("control_net_name", "")
                    if name:
                        required_models.append({"type": "controlnet", "name": name})
                elif "UNETLoader" in ctype:
                    name = inputs.get("unet_name", "")
                    if name:
                        required_models.append({"type": "unet", "name": name})

        node_list = sorted(node_types)
        summary = (
            f"{len(workflow)} nodes, {len(required_models)} model reference(s). "
            f"Node types: {', '.join(node_list[:10])}{'...' if len(node_list) > 10 else ''}."
        )
        return {"ok": True, "required_models": required_models,
                "node_types": node_list, "summary": summary}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def deploy_workflow(workflow: dict, client_id: str = "goldberg") -> dict:
    """
    Submit a workflow to the running ComfyUI instance.

    Args:
        workflow:  ComfyUI API-format prompt dict ({"node_id": {"class_type": ...}})
        client_id: identifier for this submission (default: "goldberg")

    Returns:
        {"ok": True, "prompt_id": "...", "queue_position": N}
    """
    try:
        payload = {"prompt": workflow, "client_id": client_id}
        r = httpx.post(
            f"{_COMFYUI_BASE}/api/prompt",
            json=payload,
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            return {
                "ok":            True,
                "prompt_id":     data.get("prompt_id"),
                "queue_position": data.get("number", 0),
            }
        return {"ok": False, "error": f"ComfyUI HTTP {r.status_code}: {r.text[:300]}"}

    except httpx.ConnectError:
        return {"ok": False, "error": "ComfyUI not running at 127.0.0.1:8188"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
