"""
model_manager.py — Goldberg's model intelligence layer

Responsibilities:
  1. Know what models are on the Z Slim drive
  2. Detect what a workflow needs vs what's available
  3. Auto-download missing models from CivitAI to Z Slim
  4. Track model health (problems, bad outputs, crashes)
  5. Suggest and substitute better models when one has issues

Health database: ~/.goldberg/model_health.json
Download target: /Volumes/Z Slim/AI/models/{type}/
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from .base_tool import BaseTool, ToolError
from .civitai_tool import CivitAITool, _load_api_key, _headers, CIVITAI_BASE, DL_TIMEOUT

logger = logging.getLogger("goldberg.tools.model_manager")

# ── Paths ──────────────────────────────────────────────────────────────────────

SLIM_DRIVE       = Path("/Volumes/Z Slim/AI/models")
COMFYUI_BASE     = "http://localhost:8188"
HEALTH_DB_PATH   = Path.home() / ".goldberg" / "model_health.json"

# Map ComfyUI model type names → folder names on Z Slim
TYPE_TO_FOLDER: dict[str, str] = {
    "checkpoints":      "checkpoints",
    "diffusion_models": "diffusion_models",
    "text_encoders":    "text_encoders",
    "clip":             "text_encoders",   # alias
    "loras":            "loras",
    "vae":              "vaes",
    "vaes":             "vaes",
    "controlnet":       "controlnet",
    "embeddings":       "embeddings",
    "upscale_models":   "upscale_models",
    "clip_vision":      "clip_vision",
    "ipadapter":        "ipadapter",
    "video_models":     "video_models",
    "unet":             "diffusion_models",
}

# CivitAI model_type for search queries
FOLDER_TO_CIVITAI_TYPE: dict[str, str] = {
    "checkpoints":      "Checkpoint",
    "diffusion_models": "Checkpoint",
    "loras":            "LORA",
    "vaes":             "VAE",
    "controlnet":       "ControlNet",
    "embeddings":       "TextualInversion",
    "upscale_models":   "Upscaler",
}

MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".bin", ".gguf"}


# ── Health DB ─────────────────────────────────────────────────────────────────

def _load_health_db() -> dict:
    HEALTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if HEALTH_DB_PATH.exists():
        try:
            return json.loads(HEALTH_DB_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "models": {}}


def _save_health_db(db: dict) -> None:
    HEALTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_DB_PATH.write_text(json.dumps(db, indent=2))


def _model_key(model_type: str, filename: str) -> str:
    folder = TYPE_TO_FOLDER.get(model_type, model_type)
    return f"{folder}/{filename}"


# ── ModelManager tool ─────────────────────────────────────────────────────────

class ModelManager(BaseTool):
    """
    Intelligent model management for Goldberg.

    Knows what's on disk, what workflows need, downloads missing models from
    CivitAI, tracks model health, and substitutes bad models with better ones.
    """

    name = "model_manager"
    description = (
        "Manage ComfyUI models on the Z Slim drive: scan what's available, detect "
        "missing models for a workflow, auto-download from CivitAI, track model problems, "
        "and substitute bad models with better alternatives."
    )

    def run(self, input: dict[str, Any]) -> dict[str, Any]:
        action = input.get("action", "").lower().strip()
        dispatch = {
            "scan":             self._scan,
            "check_workflow":   self._check_workflow,
            "resolve_missing":  self._resolve_missing,
            "download":         self._download_model,
            "report_problem":   self._report_problem,
            "suggest":          self._suggest_replacement,
            "health_report":    self._health_report,
            "mark_ok":          self._mark_ok,
        }
        if action not in dispatch:
            raise ToolError(
                f"model_manager: unknown action '{action}'. "
                f"Use: {', '.join(dispatch)}"
            )
        return dispatch[action](input)

    # ── 1. Scan ───────────────────────────────────────────────────────────────

    def _scan(self, _: dict) -> dict:
        """Inventory all models on Z Slim drive, grouped by type."""
        if not SLIM_DRIVE.exists():
            return {"ok": False, "error": "Z Slim drive not mounted at /Volumes/Z Slim"}

        inventory: dict[str, list] = {}
        total = 0

        for folder in sorted(SLIM_DRIVE.iterdir()):
            if not folder.is_dir():
                continue
            files = []
            for f in sorted(folder.iterdir()):
                if f.suffix in MODEL_EXTENSIONS and not f.name.startswith("._"):
                    size_gb = round(f.stat().st_size / (1024 ** 3), 2)
                    files.append({"name": f.name, "size_gb": size_gb})
                    total += 1
            if files:
                inventory[folder.name] = files

        return {
            "ok":        True,
            "drive":     str(SLIM_DRIVE),
            "total":     total,
            "inventory": inventory,
        }

    # ── 2. Check workflow ─────────────────────────────────────────────────────

    def _check_workflow(self, input: dict) -> dict:
        """
        Validate a workflow against ComfyUI to find missing models.
        Pass workflow as JSON string or dict under 'workflow' key.
        """
        workflow = input.get("workflow")
        if not workflow:
            raise ToolError("model_manager check_workflow: 'workflow' is required")
        if isinstance(workflow, str):
            try:
                workflow = json.loads(workflow)
            except json.JSONDecodeError as e:
                raise ToolError(f"model_manager check_workflow: invalid JSON — {e}")

        try:
            r = httpx.post(
                f"{COMFYUI_BASE}/api/prompt",
                json={"prompt": workflow, "client_id": "goldberg-check"},
                timeout=15.0,
            )
            data = r.json()
        except Exception as e:
            return {"ok": False, "error": f"ComfyUI unreachable: {e}"}

        # ComfyUI returns error details including missing nodes/models
        errors = data.get("error") or {}
        node_errors = data.get("node_errors") or {}

        missing_models: list[dict] = []
        missing_nodes:  list[str] = []

        for node_id, node_err in node_errors.items():
            errs = node_err.get("errors", [])
            for e in errs:
                msg = e.get("message", "")
                detail = e.get("details", "")
                if "not found" in msg.lower() or "invalid" in msg.lower():
                    # Try to extract model name from detail
                    missing_models.append({
                        "node_id":  node_id,
                        "message":  msg,
                        "detail":   detail,
                    })

        # Check health DB for any models with known issues
        db = _load_health_db()
        flagged: list[dict] = []
        for model_key, info in db["models"].items():
            if info.get("status") in ("problematic", "banned"):
                flagged.append({
                    "model":       model_key,
                    "status":      info["status"],
                    "issues":      info.get("issues", []),
                    "replacement": info.get("replacement"),
                })

        return {
            "ok":             True,
            "prompt_id":      data.get("prompt_id"),
            "missing_models": missing_models,
            "missing_nodes":  missing_nodes,
            "flagged_models": flagged,
            "queued":         "prompt_id" in data,
        }

    # ── 3. Resolve missing ────────────────────────────────────────────────────

    def _resolve_missing(self, input: dict) -> dict:
        """
        Given a list of missing model specs, find and download the best version.

        input:
          missing: list of {filename, model_type} dicts
          auto_download: bool (default True)
        """
        missing = input.get("missing", [])
        auto_download = input.get("auto_download", True)

        if not missing:
            return {"ok": True, "message": "No missing models to resolve", "resolved": []}

        db        = _load_health_db()
        civitai   = CivitAITool()
        resolved  = []
        failed    = []

        for item in missing:
            filename   = item.get("filename", "")
            model_type = item.get("model_type", "checkpoints")
            model_key  = _model_key(model_type, filename)

            # Check if it's banned — skip entirely
            if db["models"].get(model_key, {}).get("status") == "banned":
                replacement = db["models"][model_key].get("replacement")
                logger.warning(f"[model_manager] {filename} is banned. Replacement: {replacement}")
                resolved.append({
                    "filename":    filename,
                    "action":      "skipped_banned",
                    "replacement": replacement,
                })
                continue

            # Check health DB for a known replacement
            if db["models"].get(model_key, {}).get("status") == "problematic":
                replacement = db["models"][model_key].get("replacement")
                if replacement:
                    logger.info(f"[model_manager] {filename} is problematic, substituting {replacement}")
                    resolved.append({
                        "filename":    filename,
                        "action":      "substituted",
                        "replacement": replacement,
                        "reason":      db["models"][model_key].get("replacement_reason", ""),
                    })
                    continue

            # Search CivitAI for the model
            query = Path(filename).stem.replace("_", " ").replace("-", " ")
            civitai_type = FOLDER_TO_CIVITAI_TYPE.get(
                TYPE_TO_FOLDER.get(model_type, model_type), "Checkpoint"
            )
            search_result = civitai.run({"action": "search", "query": query,
                                         "model_type": civitai_type, "limit": 5})

            if not search_result.get("ok") or not search_result.get("results"):
                logger.warning(f"[model_manager] CivitAI: no results for '{query}'")
                failed.append({"filename": filename, "reason": "not found on CivitAI"})
                continue

            # Pick top result
            top = search_result["results"][0]
            version_id = top.get("version_id")

            # Get download URL
            info = civitai.run({"action": "model_info", "model_id": top["id"]})
            if not info.get("ok"):
                failed.append({"filename": filename, "reason": "could not fetch model info"})
                continue

            download_url = None
            dl_filename  = filename
            for v in info.get("versions", []):
                if v["version_id"] == version_id:
                    for f in v.get("files", []):
                        if f.get("type") in ("Model", "Pruned Model", ""):
                            download_url = f.get("download_url")
                            if f.get("name"):
                                dl_filename = f["name"]
                            break
                    break

            if not download_url:
                failed.append({"filename": filename, "reason": "no download URL found"})
                continue

            if auto_download:
                folder = TYPE_TO_FOLDER.get(model_type, model_type)
                dest   = SLIM_DRIVE / folder / dl_filename

                if dest.exists():
                    resolved.append({
                        "filename": filename,
                        "action":   "already_exists",
                        "path":     str(dest),
                    })
                    continue

                logger.info(f"[model_manager] Downloading {dl_filename} → {dest}")
                dl_result = civitai.run({
                    "action":       "download",
                    "download_url": download_url,
                    "filename":     dl_filename,
                    "model_type":   folder,
                })
                if dl_result.get("ok"):
                    resolved.append({
                        "filename":    filename,
                        "action":      "downloaded",
                        "path":        dl_result.get("path"),
                        "size_mb":     dl_result.get("size_mb"),
                        "civitai_match": top["name"],
                    })
                else:
                    failed.append({"filename": filename, "reason": dl_result.get("error")})
            else:
                resolved.append({
                    "filename":      filename,
                    "action":        "found",
                    "download_url":  download_url,
                    "civitai_match": top["name"],
                })

        return {
            "ok":       True,
            "resolved": resolved,
            "failed":   failed,
            "summary":  f"{len(resolved)} resolved, {len(failed)} failed",
        }

    # ── 4. Direct download ────────────────────────────────────────────────────

    def _download_model(self, input: dict) -> dict:
        """Download a specific model by CivitAI URL or model ID directly to Z Slim."""
        download_url = input.get("download_url", "")
        filename     = input.get("filename", "")
        model_type   = input.get("model_type", "checkpoints")
        model_id     = input.get("model_id")

        if not SLIM_DRIVE.exists():
            return {"ok": False, "error": "Z Slim drive not mounted"}

        # If given model_id, look up the download URL
        if model_id and not download_url:
            civitai = CivitAITool()
            info = civitai.run({"action": "model_info", "model_id": model_id})
            if not info.get("ok"):
                return {"ok": False, "error": f"Could not fetch model {model_id} from CivitAI"}
            versions = info.get("versions", [])
            if not versions:
                return {"ok": False, "error": "No versions found for this model"}
            first_file = (versions[0].get("files") or [{}])[0]
            download_url = first_file.get("download_url", "")
            if not filename:
                filename = first_file.get("name", f"model_{model_id}.safetensors")

        if not download_url:
            raise ToolError("model_manager download: 'download_url' or 'model_id' is required")

        folder = TYPE_TO_FOLDER.get(model_type, model_type)
        dest_dir = SLIM_DRIVE / folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = download_url.split("/")[-1].split("?")[0]

        dest = dest_dir / filename
        if dest.exists():
            return {
                "ok":      True,
                "skipped": True,
                "message": f"Already exists: {dest}",
                "path":    str(dest),
            }

        logger.info(f"[model_manager] downloading {filename} to {dest}")
        try:
            with httpx.stream(
                "GET", download_url,
                headers=_headers(),
                timeout=DL_TIMEOUT,
                follow_redirects=True,
            ) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)

            size_mb = round(dest.stat().st_size / (1024 * 1024), 1)
            logger.info(f"[model_manager] download complete: {filename} ({size_mb} MB)")
            return {
                "ok":       True,
                "filename": filename,
                "path":     str(dest),
                "size_mb":  size_mb,
                "message":  f"Downloaded {filename} ({size_mb} MB) → {folder}/",
            }
        except Exception as e:
            if dest.exists():
                dest.unlink()
            return {"ok": False, "error": str(e)}

    # ── 5. Report problem ─────────────────────────────────────────────────────

    def _report_problem(self, input: dict) -> dict:
        """
        Mark a model as problematic. Goldberg calls this when he observes bad outputs.

        input:
          filename:           "bad_model.safetensors"
          model_type:         "checkpoints"
          issues:             ["blurry outputs", "crashes on MPS at high res"]
          replacement:        "z_image_turbo_bf16.safetensors"   (optional)
          replacement_type:   "checkpoints"                       (optional)
          replacement_reason: "Sharper, more stable on Apple Silicon"
          severity:           "warn" | "ban"  (default "warn")
        """
        filename  = input.get("filename", "")
        model_type = input.get("model_type", "checkpoints")
        if not filename:
            raise ToolError("model_manager report_problem: 'filename' is required")

        db  = _load_health_db()
        key = _model_key(model_type, filename)

        replacement      = input.get("replacement")
        replacement_type = input.get("replacement_type", model_type)
        replacement_key  = _model_key(replacement_type, replacement) if replacement else None

        severity = input.get("severity", "warn")
        status   = "banned" if severity == "ban" else "problematic"

        db["models"][key] = {
            "status":             status,
            "issues":             input.get("issues", []),
            "reported_at":        datetime.now(timezone.utc).isoformat(),
            "replacement":        replacement_key,
            "replacement_reason": input.get("replacement_reason", ""),
        }

        # Also mark replacement as known-good if specified
        if replacement_key and replacement_key not in db["models"]:
            db["models"][replacement_key] = {
                "status":      "ok",
                "notes":       f"Recommended as replacement for {filename}",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

        _save_health_db(db)
        logger.info(f"[model_manager] marked {key} as {status}")

        return {
            "ok":         True,
            "model":      key,
            "status":     status,
            "issues":     input.get("issues", []),
            "replacement": replacement_key,
            "message":    (
                f"{filename} marked as {status}. "
                + (f"Replacement: {replacement_key}" if replacement_key else "No replacement set.")
            ),
        }

    # ── 6. Suggest replacement ────────────────────────────────────────────────

    def _suggest_replacement(self, input: dict) -> dict:
        """
        Given a model with problems, find the best available replacement.
        Checks health DB first, then searches CivitAI.

        input:
          filename:    "bad_model.safetensors"
          model_type:  "checkpoints"
          description: optional — describe what you need ("anime SDXL, realistic")
        """
        filename   = input.get("filename", "")
        model_type = input.get("model_type", "checkpoints")
        description = input.get("description", "")

        db  = _load_health_db()
        key = _model_key(model_type, filename)

        # Check if we already have a replacement recorded
        record = db["models"].get(key, {})
        if record.get("replacement"):
            replacement_key = record["replacement"]
            replacement_record = db["models"].get(replacement_key, {})
            return {
                "ok":             True,
                "source":         "health_db",
                "replacement":    replacement_key,
                "status":         replacement_record.get("status", "unknown"),
                "reason":         record.get("replacement_reason", ""),
                "on_disk":        (SLIM_DRIVE / replacement_key).exists(),
            }

        # Search CivitAI for something better
        query = description or Path(filename).stem.replace("_", " ").replace("-", " ")
        civitai_type = FOLDER_TO_CIVITAI_TYPE.get(
            TYPE_TO_FOLDER.get(model_type, model_type), "Checkpoint"
        )
        civitai = CivitAITool()
        results = civitai.run({
            "action":     "search",
            "query":      query,
            "model_type": civitai_type,
            "limit":      5,
            "sort":       "Highest Rated",
        })

        if not results.get("ok") or not results.get("results"):
            return {"ok": False, "error": "No replacements found on CivitAI"}

        # Filter out known-bad models
        candidates = []
        for r in results["results"]:
            candidate_key = _model_key(
                model_type,
                f"{r['name'].replace(' ', '_')}.safetensors"
            )
            if db["models"].get(candidate_key, {}).get("status") not in ("problematic", "banned"):
                candidates.append(r)

        if not candidates:
            return {"ok": False, "error": "All candidates are in the problematic list"}

        top = candidates[0]
        return {
            "ok":            True,
            "source":        "civitai",
            "replacement":   top["name"],
            "civitai_id":    top["id"],
            "version_id":    top.get("version_id"),
            "rating":        top.get("rating"),
            "downloads":     top.get("downloads"),
            "base_model":    top.get("base_model"),
            "url":           top.get("url"),
            "message":       (
                f"Suggested: {top['name']} (rated {top.get('rating', 'N/A')}, "
                f"{top.get('downloads', 0):,} downloads). "
                f"Use action=download with model_id={top['id']} to install."
            ),
        }

    # ── 7. Health report ──────────────────────────────────────────────────────

    def _health_report(self, _: dict) -> dict:
        """Show all tracked models with their health status."""
        db = _load_health_db()
        models = db.get("models", {})

        ok_models          = {k: v for k, v in models.items() if v.get("status") == "ok"}
        problematic_models = {k: v for k, v in models.items() if v.get("status") == "problematic"}
        banned_models      = {k: v for k, v in models.items() if v.get("status") == "banned"}

        return {
            "ok":          True,
            "total":       len(models),
            "ok_count":    len(ok_models),
            "problematic": problematic_models,
            "banned":      banned_models,
            "verified_ok": ok_models,
        }

    # ── 8. Mark OK ────────────────────────────────────────────────────────────

    def _mark_ok(self, input: dict) -> dict:
        """Mark a model as verified working — clears any problem flags."""
        filename   = input.get("filename", "")
        model_type = input.get("model_type", "checkpoints")
        notes      = input.get("notes", "")

        if not filename:
            raise ToolError("model_manager mark_ok: 'filename' is required")

        db  = _load_health_db()
        key = _model_key(model_type, filename)

        db["models"][key] = {
            "status":      "ok",
            "notes":       notes,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_health_db(db)

        return {"ok": True, "model": key, "status": "ok"}
