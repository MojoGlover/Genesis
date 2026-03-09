"""
RunPod Router - intelligent task routing between local Ollama and RunPod GPU cloud.

Decision logic:
- Small tasks (short text, quick code) -> local Ollama (free, instant)  
- Heavy tasks (image gen, large models, fine-tuning) -> RunPod (paid, powerful)
- Auto-fallback: if RunPod fails -> local Ollama
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional, Callable
from .worker import RunPodWorker
from .endpoints import PRESET_ENDPOINTS

logger = logging.getLogger(__name__)


class RunPodRouter:
    """
    Routes AI tasks between local Ollama and RunPod GPU cloud.
    
    Usage:
        router = RunPodRouter(api_key="rp_...")
        result = router.route_image_gen("a cat on mars, photorealistic")
        result = router.route_transcription("https://example.com/audio.mp3")
        result = router.route_heavy_llm("Analyze this 50-page document...")
    """

    # Token threshold: above this, consider offloading to larger model
    HEAVY_LLM_THRESHOLD = 2000  # chars

    def __init__(self, api_key: Optional[str] = None, local_chat_fn: Optional[Callable] = None):
        self.worker = RunPodWorker(api_key)
        self.local_chat_fn = local_chat_fn  # fn(prompt: str) -> str for local fallback

    def route_image_gen(self, prompt: str, negative_prompt: str = "", width: int = 1024, height: int = 1024) -> Dict[str, Any]:
        """Generate an image. Always uses RunPod (no local equivalent)."""
        return self.worker.run("stable_diffusion", {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "num_steps": 30,
        })

    def route_transcription(self, audio_url: str, language: str = "en") -> Dict[str, Any]:
        """Transcribe audio. Uses RunPod Whisper."""
        return self.worker.run("whisper", {
            "audio_url": audio_url,
            "language": language,
            "model": "large-v3",
        })

    def route_heavy_llm(self, prompt: str, system: str = "", max_tokens: int = 2048) -> Dict[str, Any]:
        """
        Route to large LLM. Uses local Ollama for short prompts,
        RunPod 70B for complex/long tasks.
        """
        if len(prompt) < self.HEAVY_LLM_THRESHOLD and self.local_chat_fn:
            # Short enough for local
            try:
                result = self.local_chat_fn(prompt)
                return {"success": True, "output": result, "source": "local_ollama"}
            except Exception as e:
                logger.warning(f"Local LLM failed, falling back to RunPod: {e}")

        # Heavy task or local failed -> RunPod
        result = self.worker.run("llama70b", {
            "prompt": prompt,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        })
        if result.get("success"):
            result["source"] = "runpod_70b"
        elif self.local_chat_fn:
            # Final fallback to local
            try:
                result = {"success": True, "output": self.local_chat_fn(prompt), "source": "local_fallback"}
            except Exception as e:
                result["error"] = str(e)
        return result

    def route_task(self, task_type: str, **kwargs) -> Dict[str, Any]:
        """
        Generic task router.
        
        task_type: "image", "transcribe", "llm", "comfyui", or any RunPod endpoint name
        """
        routes = {
            "image": self.route_image_gen,
            "transcribe": self.route_transcription,
            "llm": self.route_heavy_llm,
        }
        if task_type in routes:
            return routes[task_type](**kwargs)
        # Try direct RunPod endpoint
        return self.worker.run(task_type, kwargs)

    def get_status(self) -> dict:
        return {
            "worker": self.worker.get_status(),
            "local_llm": "configured" if self.local_chat_fn else "not wired",
            "heavy_llm_threshold_chars": self.HEAVY_LLM_THRESHOLD,
        }
