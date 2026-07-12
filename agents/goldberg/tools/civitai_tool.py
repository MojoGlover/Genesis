"""
civitai_tool.py — Goldberg's CivitAI integration tool

Fetch workflows, search models, download checkpoints/LoRAs from CivitAI.
API key is read from Cerberus config at:
  ~/ai/cmptrblk/Cerberus/config.yaml → vault.civitai_api_key

TODO: once Cerberus vault API is built, replace direct config read with:
  GET http://localhost:8200/api/vault/secret?service=civitai
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import httpx
import yaml

from .base_tool import BaseTool

logger = logging.getLogger("goldberg.tools.civitai")

CIVITAI_BASE  = "https://civitai.com/api/v1"
COMFYUI_ROOT  = Path.home() / "ai/art/ComfyUI"
CERBERUS_CFG  = Path.home() / "ai/cmptrblk/Cerberus/config.yaml"
TIMEOUT       = 30.0
DL_TIMEOUT    = 600.0  # model downloads can be large


def _load_api_key() -> str:
    """Read CivitAI API key from Cerberus vault section."""
    if not CERBERUS_CFG.exists():
        raise RuntimeError(f"Cerberus config not found at {CERBERUS_CFG}")
    with CERBERUS_CFG.open() as f:
        cfg = yaml.safe_load(f)
    key = (cfg.get("vault") or {}).get("civitai_api_key", "")
    if not key:
        raise RuntimeError("vault.civitai_api_key not set in Cerberus config.yaml")
    return key


def _headers() -> dict:
    return {"Authorization": f"Bearer {_load_api_key()}"}


class CivitAITool(BaseTool):
    """Search, inspect, and download models/workflows from CivitAI."""

    name        = "civitai"
    description = (
        "Interact with CivitAI: search models, download checkpoints/LoRAs into ComfyUI, "
        "fetch and analyze workflows from shared images."
    )

    def execute(self, action: str, **kwargs) -> dict[str, Any]:
        """
        Actions:
            search          — search CivitAI for models
            model_info      — get details on a specific model by ID
            download        — download a model into ComfyUI models dir
            list_local      — list models currently on disk in ComfyUI
            fetch_workflow  — fetch workflow JSON from a CivitAI image URL (if embedded)
        """
        action = action.lower().strip()
        dispatch = {
            "search":         self._search,
            "model_info":     self._model_info,
            "download":       self._download,
            "list_local":     self._list_local,
            "fetch_workflow": self._fetch_workflow,
        }
        if action not in dispatch:
            return {"error": f"Unknown action '{action}'. Use: {', '.join(dispatch)}"}
        try:
            return dispatch[action](**kwargs)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

    # ── Actions ────────────────────────────────────────────────────────────────

    def _search(
        self,
        query: str = "",
        model_type: str = "Checkpoint",
        limit: int = 10,
        nsfw: bool = False,
        sort: str = "Most Downloaded",
        **_,
    ) -> dict:
        """
        Search CivitAI models.
        model_type options: Checkpoint, LORA, TextualInversion, VAE, ControlNet, etc.
        sort options: Most Downloaded, Highest Rated, Newest
        """
        params = {
            "limit": limit,
            "types": model_type,
            "nsfw":  str(nsfw).lower(),
            "sort":  sort,
        }
        if query:
            params["query"] = query

        try:
            r = httpx.get(
                f"{CIVITAI_BASE}/models",
                params=params,
                headers=_headers(),
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            results = []
            for m in data.get("items", []):
                latest = (m.get("modelVersions") or [{}])[0]
                results.append({
                    "id":          m["id"],
                    "name":        m["name"],
                    "type":        m.get("type"),
                    "rating":      m.get("stats", {}).get("rating"),
                    "downloads":   m.get("stats", {}).get("downloadCount"),
                    "version_id":  latest.get("id"),
                    "version":     latest.get("name"),
                    "base_model":  latest.get("baseModel"),
                    "url":         f"https://civitai.com/models/{m['id']}",
                })
            return {"ok": True, "count": len(results), "results": results}
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"CivitAI API error: {e.response.status_code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _model_info(self, model_id: int | str, **_) -> dict:
        """Get full details on a model including all versions and download URLs."""
        try:
            r = httpx.get(
                f"{CIVITAI_BASE}/models/{model_id}",
                headers=_headers(),
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            m = r.json()
            versions = []
            for v in m.get("modelVersions", []):
                files = [
                    {
                        "name":        f["name"],
                        "size_mb":     round(f.get("sizeKB", 0) / 1024, 1),
                        "download_url": f.get("downloadUrl", ""),
                        "type":        f.get("type", ""),
                    }
                    for f in v.get("files", [])
                ]
                versions.append({
                    "version_id":  v["id"],
                    "version":     v["name"],
                    "base_model":  v.get("baseModel"),
                    "files":       files,
                })
            return {
                "ok":      True,
                "id":      m["id"],
                "name":    m["name"],
                "type":    m.get("type"),
                "versions": versions,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _download(
        self,
        download_url: str = "",
        filename: str = "",
        model_type: str = "checkpoints",
        **_,
    ) -> dict:
        """
        Download a model file into the correct ComfyUI models subfolder.
        model_type: checkpoints, loras, vae, controlnet, embeddings, upscale_models
        """
        if not download_url:
            return {"error": "download_url is required"}
        if not filename:
            filename = download_url.split("/")[-1].split("?")[0]
            if not filename.endswith((".safetensors", ".ckpt", ".pt", ".bin")):
                filename += ".safetensors"

        dest_dir = COMFYUI_ROOT / "models" / model_type
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename

        if dest.exists():
            return {
                "ok":      True,
                "message": f"Already exists: {dest}",
                "path":    str(dest),
                "skipped": True,
            }

        logger.info(f"[civitai] downloading {filename} → {dest}")
        try:
            with httpx.stream(
                "GET", download_url, headers=_headers(), timeout=DL_TIMEOUT, follow_redirects=True
            ) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)

            size_mb = round(dest.stat().st_size / (1024 * 1024), 1)
            logger.info(f"[civitai] download complete: {filename} ({size_mb} MB)")
            return {
                "ok":       True,
                "filename": filename,
                "path":     str(dest),
                "size_mb":  size_mb,
                "message":  f"Downloaded {filename} ({size_mb} MB) to {model_type}/",
            }
        except Exception as e:
            if dest.exists():
                dest.unlink()  # clean up partial download
            return {"ok": False, "error": str(e)}

    def _list_local(self, model_type: str = "checkpoints", **_) -> dict:
        """List model files currently on disk in a ComfyUI models subfolder."""
        folder = COMFYUI_ROOT / "models" / model_type
        if not folder.exists():
            return {"ok": False, "error": f"Folder not found: {folder}"}
        files = []
        for f in sorted(folder.iterdir()):
            if f.suffix in (".safetensors", ".ckpt", ".pt", ".bin") and not f.name.startswith("put_"):
                files.append({
                    "name":    f.name,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                })
        return {"ok": True, "folder": model_type, "count": len(files), "files": files}

    def _fetch_workflow(self, image_url: str = "", **_) -> dict:
        """
        Attempt to fetch embedded workflow JSON from a CivitAI image URL.
        CivitAI stores workflow metadata on image pages via their API.
        """
        if not image_url:
            return {"error": "image_url is required"}

        # Extract image ID from URL if full URL given
        # e.g. https://civitai.com/images/12345
        image_id = image_url.rstrip("/").split("/")[-1]
        if not image_id.isdigit():
            return {"error": f"Could not parse image ID from URL: {image_url}"}

        try:
            r = httpx.get(
                f"{CIVITAI_BASE}/images/{image_id}",
                headers=_headers(),
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            meta = data.get("meta") or {}
            workflow = meta.get("workflow") or meta.get("comfyWorkflow")
            if workflow:
                return {
                    "ok":       True,
                    "image_id": image_id,
                    "workflow": workflow,
                    "message":  "Workflow JSON retrieved. Use comfyui tool with action=generate or paste into ComfyUI.",
                }
            else:
                return {
                    "ok":      False,
                    "image_id": image_id,
                    "message": "No workflow embedded in this image. Try a different image or use the model directly.",
                    "meta":    meta,
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}
