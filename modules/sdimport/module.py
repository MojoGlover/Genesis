"""
sdimport — GENESIS Module

Self-registering module: image generation metadata importer → ComfyUI workflow JSON.

The ModuleRegistry discovers this file because it:
  - Lives at modules/sdimport/module.py
  - Exports a class named `Module` that subclasses ModuleBase

Endpoints (mounted at startup, zero app.py changes needed):
    POST /sdimport/import   Extract params from URL or local PNG, return workflow JSON
    POST /sdimport/save     Persist a workflow dict to disk

ToolRegistry tools (available to all GENESIS agents after startup):
    sdimport_extract(source, build_workflow=True) → dict
    sdimport_save_workflow(workflow, filename=None, output_dir=None) → str (path)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from agents.tools.tool_registry import register_tool
from modules.base import ModuleBase

from .extractor import extract, build_comfyui_workflow
from .schemas import ImportRequest, ImportResponse, SaveRequest, SaveResponse

logger = logging.getLogger(__name__)

# Default save location — used when no output_dir is specified
_COMFYUI_WORKFLOWS = Path("/Users/darnieglover/ai/art/ComfyUI/user/default/workflows")


# ---------------------------------------------------------------------------
# Tool functions — registered globally at import time via @register_tool.
# Defined at module level so they're in place before Module() is instantiated,
# consistent with how agents/tools/__init__.py works.
# ---------------------------------------------------------------------------

@register_tool(
    name="sdimport_extract",
    description=(
        "Extract image generation metadata from a Civitai URL, PromptHero URL, "
        "Lexica URL, direct image URL, or local PNG file. Returns a dict with "
        "positive prompt, negative prompt, model, steps, cfg, seed, sampler, "
        "scheduler, width, height, and optionally a ComfyUI workflow JSON."
    ),
    category="image_gen",
    examples=[
        "sdimport_extract('https://civitai.com/images/12345678')",
        "sdimport_extract('./my_image.png', build_workflow=True)",
    ],
)
def sdimport_extract(source: str, build_workflow: bool = True) -> Dict[str, Any]:
    """Extract generation metadata from a URL or local PNG."""
    params = extract(source)
    result = params.to_dict()
    if build_workflow:
        result["workflow"] = build_comfyui_workflow(params)
    return result


@register_tool(
    name="sdimport_save_workflow",
    description=(
        "Save a ComfyUI workflow dict to a JSON file on disk. "
        "Saves to the ComfyUI workflows directory if it exists, otherwise cwd. "
        "Returns the absolute path to the saved file."
    ),
    category="image_gen",
    examples=[
        "sdimport_save_workflow(workflow_dict)",
        "sdimport_save_workflow(workflow_dict, filename='my_workflow.json')",
        "sdimport_save_workflow(workflow_dict, output_dir='/tmp/workflows')",
    ],
)
def sdimport_save_workflow(
    workflow: Dict[str, Any],
    filename: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """Save a ComfyUI workflow dict to disk. Returns the saved file path."""
    out_dir = Path(output_dir) if output_dir else (
        _COMFYUI_WORKFLOWS if _COMFYUI_WORKFLOWS.exists() else Path.cwd()
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    fname = filename or "sdimport_workflow.json"
    if not fname.endswith(".json"):
        fname += ".json"

    out_path = out_dir / fname
    out_path.write_text(json.dumps(workflow, indent=2))
    logger.debug(f"[sdimport] Saved workflow to {out_path}")
    return str(out_path)


# ---------------------------------------------------------------------------
# Module class — discovered and instantiated by ModuleRegistry
# ---------------------------------------------------------------------------

class Module(ModuleBase):
    """sdimport capability module."""

    def __init__(self) -> None:
        self._router        = self._build_router()
        self._import_count  = 0
        self._error_count   = 0
        self._last_import:  Optional[datetime] = None

    # ------------------------------------------------------------------
    # ModuleBase required properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "sdimport"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return (
            "Import image generation metadata from Civitai, PromptHero, Lexica, "
            "direct image URLs, or local PNG files into ComfyUI workflow JSON format."
        )

    @property
    def tags(self) -> List[str]:
        return ["sdimport", "comfyui", "image-gen"]

    @property
    def router(self) -> APIRouter:
        return self._router

    @property
    def tools(self) -> List:
        # Already registered at module-level via @register_tool.
        # Returning them here lets the registry validate they landed correctly.
        return [sdimport_extract, sdimport_save_workflow]

    @property
    def agents(self) -> List:
        return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """Validate soft dependencies and log readiness."""
        missing = []
        try:
            import requests  # noqa: F401
        except ImportError:
            missing.append("requests")
        try:
            import bs4  # noqa: F401
        except ImportError:
            missing.append("beautifulsoup4")

        if missing:
            logger.warning(
                f"[sdimport] Missing optional dependencies: {', '.join(missing)}. "
                f"URL extraction will fail for sites requiring these. "
                f"Install with: pip install {' '.join(missing)}"
            )
        else:
            logger.info("[sdimport] All dependencies present. Module ready.")

    async def on_shutdown(self) -> None:
        logger.info(
            f"[sdimport] Shutting down. "
            f"Total imports: {self._import_count}, errors: {self._error_count}"
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        return {
            "status":       "ok",
            "module":       self.name,
            "version":      self.version,
            "import_count": self._import_count,
            "error_count":  self._error_count,
            "last_import":  (
                self._last_import.isoformat()
                if self._last_import else None
            ),
        }

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    def _build_router(self) -> APIRouter:
        router = APIRouter(prefix="/sdimport", tags=["sdimport", "comfyui"])

        @router.post("/import", response_model=ImportResponse)
        async def import_metadata(req: ImportRequest) -> ImportResponse:
            """
            Extract image generation metadata from a URL or local PNG file.

            Supported sources:
            - `https://civitai.com/images/<id>` — Civitai public API
            - `https://prompthero.com/prompt/<slug>` — PromptHero page scrape
            - `https://lexica.art/prompt/<id>` — Lexica API or page scrape
            - Any direct `.png` URL — downloads and reads embedded metadata
            - Local file path — reads A1111 or ComfyUI metadata from PNG

            Set `build_workflow: true` to also receive a ComfyUI workflow JSON
            ready to load in ComfyUI via File → Load.
            """
            try:
                params = extract(req.source)
            except (ValueError, IOError) as exc:
                self._error_count += 1
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except ImportError as exc:
                self._error_count += 1
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except Exception as exc:
                self._error_count += 1
                logger.error(f"[sdimport] Unexpected error: {exc}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(exc)) from exc

            workflow = build_comfyui_workflow(params) if req.build_workflow else None

            self._import_count += 1
            self._last_import = datetime.now(timezone.utc)

            return ImportResponse(
                source_type = params.source_type,
                source_url  = getattr(params, "source_url", ""),
                positive    = params.positive,
                negative    = params.negative,
                model       = params.model,
                steps       = params.steps,
                cfg         = params.cfg,
                seed        = params.seed,
                sampler     = params.sampler,
                scheduler   = params.scheduler,
                width       = params.width,
                height      = params.height,
                workflow    = workflow,
            )

        @router.post("/save", response_model=SaveResponse)
        async def save_workflow(req: SaveRequest) -> SaveResponse:
            """
            Persist a ComfyUI workflow dict to disk as a JSON file.

            If `output_dir` is not provided, saves to the ComfyUI default
            workflows directory if it exists, otherwise the current directory.

            If `filename` is not provided, it is auto-generated from the
            positive prompt text in the workflow (or 'sdimport_workflow.json').
            """
            out_dir = Path(req.output_dir) if req.output_dir else (
                _COMFYUI_WORKFLOWS
                if _COMFYUI_WORKFLOWS.exists()
                else Path.cwd()
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Cannot create output directory: {exc}",
                ) from exc

            if req.filename:
                fname = req.filename if req.filename.endswith(".json") else req.filename + ".json"
            else:
                positive = ""
                for node in req.workflow.values():
                    if (
                        isinstance(node, dict)
                        and node.get("class_type") == "CLIPTextEncode"
                        and "Positive" in node.get("_meta", {}).get("title", "")
                    ):
                        positive = node.get("inputs", {}).get("text", "")
                        break
                slug = re.sub(r"[^\w\s-]", "", positive[:40])
                slug = re.sub(r"\s+", "_", slug).strip("_").lower()
                slug = re.sub(r"_+", "_", slug) or "imported"
                fname = f"sdimport_{slug}.json"

            out_path = out_dir / fname
            try:
                out_path.write_text(json.dumps(req.workflow, indent=2))
            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Cannot write file: {exc}",
                ) from exc

            logger.info(f"[sdimport] Saved workflow → {out_path}")
            return SaveResponse(saved_path=str(out_path), filename=fname)

        return router
