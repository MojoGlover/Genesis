"""Pre-configured RunPod serverless endpoints for common AI tasks."""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class EndpointConfig:
    name: str
    endpoint_id: str          # RunPod endpoint ID (set from env or config)
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 300
    env_var: str = ""         # Env var to read endpoint_id from


# Pre-configured endpoints — set IDs via env vars or config
PRESET_ENDPOINTS = {
    "stable_diffusion": EndpointConfig(
        name="Stable Diffusion XL",
        endpoint_id="",
        description="Image generation from text prompts",
        input_schema={"prompt": str, "negative_prompt": str, "width": int, "height": int, "num_steps": int},
        timeout_seconds=120,
        env_var="RUNPOD_ENDPOINT_SDXL",
    ),
    "whisper": EndpointConfig(
        name="Whisper Large v3",
        endpoint_id="",
        description="Audio transcription",
        input_schema={"audio_url": str, "language": str, "model": str},
        timeout_seconds=180,
        env_var="RUNPOD_ENDPOINT_WHISPER",
    ),
    "llama70b": EndpointConfig(
        name="Llama 3 70B",
        endpoint_id="",
        description="Large language model for complex reasoning",
        input_schema={"prompt": str, "max_tokens": int, "temperature": float, "system": str},
        timeout_seconds=300,
        env_var="RUNPOD_ENDPOINT_LLAMA70B",
    ),
    "comfyui": EndpointConfig(
        name="ComfyUI",
        endpoint_id="",
        description="Advanced image generation with ComfyUI workflows",
        input_schema={"workflow": dict},
        timeout_seconds=600,
        env_var="RUNPOD_ENDPOINT_COMFYUI",
    ),
    "custom_training": EndpointConfig(
        name="Custom LoRA Training",
        endpoint_id="",
        description="Fine-tune models on RunPod GPU",
        input_schema={"dataset_url": str, "base_model": str, "config": dict},
        timeout_seconds=3600,
        env_var="RUNPOD_ENDPOINT_TRAINING",
    ),
}
