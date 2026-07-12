"""
replicate_tool.py — Goldberg's Replicate API integration

Cloud fallback when ComfyUI isn't running locally.
Uses Flux (schnell/dev) and SDXL for image generation.
Reports costs to PlugOps activity log.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .base_tool import BaseTool

logger = logging.getLogger("goldberg.tools.replicate")

REPLICATE_API = "https://api.replicate.com/v1"

# Model IDs and rough cost per image (USD) for cost reporting
MODELS = {
    "flux-schnell":  ("black-forest-labs/flux-schnell",  0.003),
    "flux-dev":      ("black-forest-labs/flux-dev",      0.055),
    "sdxl":          ("stability-ai/sdxl",               0.0039),
}


class ReplicateTool(BaseTool):
    """Generate images via Replicate API (cloud). Use when ComfyUI is unavailable."""

    name        = "replicate"
    description = "Generate images via Replicate cloud API (Flux, SDXL). Fallback when ComfyUI is unavailable."

    def execute(self, action: str, **kwargs) -> dict[str, Any]:
        action = action.lower().strip()
        if action == "generate":
            return self._generate(**kwargs)
        elif action == "models":
            return {"available_models": list(MODELS.keys()), "note": "flux-schnell is fastest + cheapest"}
        else:
            return {"error": f"Unknown action '{action}'. Use: generate, models"}

    def _generate(
        self,
        prompt: str = "",
        model: str = "flux-schnell",
        width: int = 1024,
        height: int = 1024,
        num_outputs: int = 1,
        **_,
    ) -> dict:
        api_token = os.environ.get("REPLICATE_API_TOKEN")
        if not api_token:
            return {"error": "REPLICATE_API_TOKEN not set. Add it to the environment."}

        if not prompt:
            return {"error": "prompt is required"}

        if model not in MODELS:
            return {"error": f"Unknown model '{model}'. Available: {list(MODELS.keys())}"}

        model_id, cost_per_image = MODELS[model]
        estimated_cost = round(cost_per_image * num_outputs, 4)

        headers = {
            "Authorization": f"Token {api_token}",
            "Content-Type":  "application/json",
        }
        payload = {
            "version": model_id,
            "input": {
                "prompt":      prompt,
                "width":       width,
                "height":      height,
                "num_outputs": num_outputs,
            },
        }

        try:
            r = httpx.post(
                f"{REPLICATE_API}/predictions",
                headers=headers, json=payload, timeout=60.0,
            )
            r.raise_for_status()
            prediction = r.json()
            pred_id = prediction.get("id")
            logger.info(f"[replicate] queued prediction={pred_id}, model={model}, est_cost=${estimated_cost}")

            return {
                "ok":             True,
                "prediction_id":  pred_id,
                "model":          model,
                "status":         prediction.get("status"),
                "estimated_cost": f"~${estimated_cost}",
                "poll_url":       prediction.get("urls", {}).get("get"),
                "message":        f"Queued on Replicate. Poll {prediction.get('urls', {}).get('get')} for results.",
            }
        except httpx.HTTPStatusError as e:
            return {"ok": False, "error": f"Replicate API error {e.response.status_code}: {e.response.text}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
