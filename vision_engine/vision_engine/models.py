"""Pydantic models for vision engine."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class VisionModel(str, Enum):
    """Available Ollama vision models."""
    LLAVA_7B = "llava:7b"
    LLAVA_13B = "llava:13b"
    LLAVA_34B = "llava:34b"
    BAKLLAVA = "bakllava"
    LLAVA_LLAMA3 = "llava-llama3"
    LLAVA_PHI3 = "llava-phi3"


class VisionResponse(BaseModel):
    """Raw response from vision model."""
    model: str
    response: str
    total_duration: Optional[int] = None
    load_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None


class ImageAnalysis(BaseModel):
    """Structured analysis of an image."""
    description: str = Field(description="Overall description of the image")
    objects: list[str] = Field(default_factory=list, description="Objects detected")
    text_content: str = Field(default="", description="Text found in image (OCR)")
    colors: list[str] = Field(default_factory=list, description="Dominant colors")
    scene_type: str = Field(default="", description="Type of scene (indoor, outdoor, etc)")
    suggestions: list[str] = Field(default_factory=list, description="AI suggestions")
    confidence: float = Field(default=0.0, description="Confidence score 0-1", ge=0, le=1)
    raw_response: str = Field(default="", description="Raw model output")


class OCRResult(BaseModel):
    """Text extraction result."""
    text: str = Field(description="Extracted text")
    confidence: float = Field(default=0.0, ge=0, le=1)
    language: str = Field(default="en")


class ObjectDetection(BaseModel):
    """Detected object in image."""
    label: str
    confidence: float = Field(ge=0, le=1)
    bounding_box: Optional[tuple[int, int, int, int]] = Field(
        default=None,
        description="(x1, y1, x2, y2) coordinates"
    )


class SceneUnderstanding(BaseModel):
    """High-level scene understanding."""
    scene_type: str = Field(description="indoor, outdoor, street, office, etc")
    activity: str = Field(default="", description="What's happening")
    context: str = Field(default="", description="Additional context")
    objects: list[ObjectDetection] = Field(default_factory=list)
    people_count: int = Field(default=0, ge=0)
