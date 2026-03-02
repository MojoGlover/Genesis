"""Pydantic v2 request/response models for the sdimport module."""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ImportRequest(BaseModel):
    """POST /sdimport/import — extract metadata from a URL or local PNG."""
    source: str = Field(
        ...,
        description=(
            "URL (Civitai/PromptHero/Lexica/direct image) or local file path. "
            "Example: 'https://civitai.com/images/12345678' or '/path/to/image.png'"
        ),
    )
    build_workflow: bool = Field(
        True,
        description="If true, also build and return a ComfyUI workflow JSON dict.",
    )


class ImportResponse(BaseModel):
    """Extracted generation metadata, optionally with a ComfyUI workflow."""
    source_type: str
    source_url:  str
    positive:    str
    negative:    str
    model:       str
    steps:       int
    cfg:         float
    seed:        int
    sampler:     str
    scheduler:   str
    width:       int
    height:      int
    workflow:    Optional[Dict[str, Any]] = Field(
        None,
        description="ComfyUI workflow JSON. Populated when build_workflow=True.",
    )


class SaveRequest(BaseModel):
    """POST /sdimport/save — persist a workflow dict to disk as JSON."""
    workflow: Dict[str, Any] = Field(
        ...,
        description="ComfyUI workflow dict (from /sdimport/import or built manually).",
    )
    filename: Optional[str] = Field(
        None,
        description=(
            "Output filename (with or without .json extension). "
            "Auto-generated from the positive prompt if omitted."
        ),
    )
    output_dir: Optional[str] = Field(
        None,
        description=(
            "Absolute path to save directory. "
            "Defaults to ComfyUI workflows dir if it exists, else cwd."
        ),
    )


class SaveResponse(BaseModel):
    """Result of saving a workflow to disk."""
    saved_path: str = Field(..., description="Absolute path to the saved JSON file.")
    filename:   str = Field(..., description="Filename of the saved JSON file.")
