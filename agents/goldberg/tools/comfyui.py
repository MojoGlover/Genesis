"""
comfyui.py — Goldberg's ComfyUI integration tool

Builds, queues, and inspects ComfyUI workflows on the local instance (localhost:8188).

Actions:
  build_workflow  — compose a node graph from a spec and submit (or just return the dict)
  generate        — shorthand: text-to-image with common params (wraps build_workflow)
  queue_workflow  — submit a pre-built workflow dict directly
  describe        — parse an existing workflow dict, return human-readable breakdown
  status          — check queue
  history         — list recent completed jobs
  health          — ping ComfyUI
"""

from __future__ import annotations

import json
import time
import uuid
import logging
from typing import Any

import httpx

from .base_tool import BaseTool

logger = logging.getLogger("goldberg.tools.comfyui")

COMFYUI_BASE = "http://localhost:8188"
TIMEOUT = 30.0

# ── Known output slot numbers (slot index → semantic name) ──────────────────
# Used in describe() to annotate links with human-readable slot names.
_NODE_OUTPUTS: dict[str, list[str]] = {
    "CheckpointLoaderSimple": ["MODEL", "CLIP", "VAE"],
    "CheckpointLoader":       ["MODEL", "CLIP", "VAE"],
    "LoraLoader":             ["MODEL", "CLIP"],
    "CLIPTextEncode":         ["CONDITIONING"],
    "KSampler":               ["LATENT"],
    "KSamplerAdvanced":       ["LATENT"],
    "EmptyLatentImage":       ["LATENT"],
    "VAEDecode":              ["IMAGE"],
    "VAEEncode":              ["LATENT"],
    "ImageScale":             ["IMAGE"],
    "ImageUpscaleWithModel":  ["IMAGE"],
    "UpscaleModelLoader":     ["UPSCALE_MODEL"],
    "ControlNetApplyAdvanced":["POSITIVE", "NEGATIVE"],
    "ControlNetLoader":       ["CONTROL_NET"],
    "LoadImage":              ["IMAGE", "MASK"],
}


class WorkflowBuilder:
    """
    Fluent builder for ComfyUI API-format workflows.

    ComfyUI API format (flat node dict):
        {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
            "2": {"class_type": "CLIPTextEncode",         "inputs": {"text": "...", "clip": ["1", 1]}},
            ...
        }

    Links: an input value of ["node_id", slot_index] wires an output from another node.
    Literal values (str, int, float, bool) go directly.

    Output slot conventions (most common):
        CheckpointLoaderSimple  → [0]=MODEL, [1]=CLIP, [2]=VAE
        LoraLoader              → [0]=MODEL, [1]=CLIP
        CLIPTextEncode          → [0]=CONDITIONING
        EmptyLatentImage        → [0]=LATENT
        KSampler                → [0]=LATENT
        VAEDecode               → [0]=IMAGE
    """

    def __init__(self) -> None:
        self._nodes: dict[str, dict] = {}
        self._next_id: int = 1

    def add(self, class_type: str, inputs: dict) -> str:
        """Add a node. Returns its auto-assigned string ID."""
        node_id = str(self._next_id)
        self._next_id += 1
        self._nodes[node_id] = {"class_type": class_type, "inputs": inputs}
        return node_id

    @staticmethod
    def ref(node_id: str, slot: int = 0) -> list:
        """Create a link reference to another node's output slot."""
        return [node_id, slot]

    def build(self) -> dict:
        """Return the complete workflow dict in ComfyUI API format."""
        return dict(self._nodes)

    # ── Standard factory methods ─────────────────────────────────────────────

    @classmethod
    def standard_t2i(
        cls,
        checkpoint: str,
        positive: str,
        negative: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg: float = 7.0,
        seed: int | None = None,
        sampler: str = "dpmpp_2m",
        scheduler: str = "karras",
        loras: list[dict] | None = None,
        filename_prefix: str = "goldberg",
    ) -> dict:
        """
        Build a standard text-to-image workflow with optional LoRA chaining.

        loras: [{"name": "style_lora.safetensors", "weight": 0.8}, ...]

        Node chain:
            CheckpointLoaderSimple
              → LoraLoader (×N, chained)
              → CLIPTextEncode ×2  (positive + negative)
              → EmptyLatentImage
              → KSampler
              → VAEDecode
              → SaveImage
        """
        b = cls()
        neg = negative or "blurry, low quality, bad anatomy, watermark, text, cropped, worst quality, jpeg artifacts"
        actual_seed = seed if seed is not None else int(time.time()) % 2**32

        ckpt_id = b.add("CheckpointLoaderSimple", {"ckpt_name": checkpoint})
        model_ref = b.ref(ckpt_id, 0)  # MODEL
        clip_ref  = b.ref(ckpt_id, 1)  # CLIP
        vae_ref   = b.ref(ckpt_id, 2)  # VAE

        for lora in (loras or []):
            lora_id = b.add("LoraLoader", {
                "model":           model_ref,
                "clip":            clip_ref,
                "lora_name":       lora["name"],
                "strength_model":  lora.get("weight", 0.8),
                "strength_clip":   lora.get("weight", 0.8),
            })
            model_ref = b.ref(lora_id, 0)
            clip_ref  = b.ref(lora_id, 1)

        latent_id = b.add("EmptyLatentImage", {"width": width, "height": height, "batch_size": 1})
        pos_id    = b.add("CLIPTextEncode", {"text": positive, "clip": clip_ref})
        neg_id    = b.add("CLIPTextEncode", {"text": neg,      "clip": clip_ref})

        ksampler_id = b.add("KSampler", {
            "model":        model_ref,
            "positive":     b.ref(pos_id, 0),
            "negative":     b.ref(neg_id, 0),
            "latent_image": b.ref(latent_id, 0),
            "seed":         actual_seed,
            "steps":        steps,
            "cfg":          cfg,
            "sampler_name": sampler,
            "scheduler":    scheduler,
            "denoise":      1.0,
        })

        vae_decode_id = b.add("VAEDecode", {
            "samples": b.ref(ksampler_id, 0),
            "vae":     vae_ref,
        })
        b.add("SaveImage", {
            "images":          b.ref(vae_decode_id, 0),
            "filename_prefix": filename_prefix,
        })
        return b.build()

    @classmethod
    def img2img(
        cls,
        checkpoint: str,
        image_path: str,
        positive: str,
        negative: str = "",
        denoise: float = 0.75,
        steps: int = 20,
        cfg: float = 7.0,
        seed: int | None = None,
        sampler: str = "dpmpp_2m",
        scheduler: str = "karras",
        loras: list[dict] | None = None,
        filename_prefix: str = "goldberg_i2i",
    ) -> dict:
        """
        Build an image-to-image workflow. Loads an image, encodes to latent, denoises.

        denoise: 0.0 = no change, 1.0 = full generation. 0.5-0.8 for reinterpretation.
        """
        b = cls()
        neg = negative or "blurry, low quality, bad anatomy, watermark, text"
        actual_seed = seed if seed is not None else int(time.time()) % 2**32

        ckpt_id = b.add("CheckpointLoaderSimple", {"ckpt_name": checkpoint})
        model_ref = b.ref(ckpt_id, 0)
        clip_ref  = b.ref(ckpt_id, 1)
        vae_ref   = b.ref(ckpt_id, 2)

        for lora in (loras or []):
            lora_id = b.add("LoraLoader", {
                "model": model_ref, "clip": clip_ref,
                "lora_name": lora["name"],
                "strength_model": lora.get("weight", 0.8),
                "strength_clip":  lora.get("weight", 0.8),
            })
            model_ref = b.ref(lora_id, 0)
            clip_ref  = b.ref(lora_id, 1)

        load_id    = b.add("LoadImage",    {"image": image_path})
        encode_id  = b.add("VAEEncode",    {"pixels": b.ref(load_id, 0), "vae": vae_ref})
        pos_id     = b.add("CLIPTextEncode", {"text": positive, "clip": clip_ref})
        neg_id     = b.add("CLIPTextEncode", {"text": neg,      "clip": clip_ref})

        ksampler_id = b.add("KSampler", {
            "model": model_ref, "positive": b.ref(pos_id, 0), "negative": b.ref(neg_id, 0),
            "latent_image": b.ref(encode_id, 0),
            "seed": actual_seed, "steps": steps, "cfg": cfg,
            "sampler_name": sampler, "scheduler": scheduler, "denoise": denoise,
        })
        vae_decode_id = b.add("VAEDecode", {"samples": b.ref(ksampler_id, 0), "vae": vae_ref})
        b.add("SaveImage", {"images": b.ref(vae_decode_id, 0), "filename_prefix": filename_prefix})
        return b.build()


class ComfyUITool(BaseTool):
    """Build, queue, and inspect ComfyUI image generation workflows."""

    name        = "comfyui"
    description = (
        "Generate images via local ComfyUI. "
        "Actions: build_workflow, generate, queue_workflow, describe, status, history, health."
    )

    def run(self, input: dict[str, Any]) -> dict[str, Any]:
        """BaseTool interface. Delegates to execute() with action from input dict."""
        action = input.pop("action", "")
        return self.execute(action, **input)

    def execute(self, action: str, **kwargs) -> dict[str, Any]:
        action = action.lower().strip()
        dispatch = {
            "generate":       self._generate,
            "build_workflow": self._build_workflow,
            "queue_workflow": self._queue_workflow,
            "describe":       self._describe,
            "status":         lambda **_: self._status(),
            "history":        lambda **kw: self._history(kw.get("limit", 10)),
            "health":         lambda **_: self._health(),
        }
        if action not in dispatch:
            return {"error": f"Unknown action '{action}'. Use: {', '.join(dispatch)}"}
        return dispatch[action](**kwargs)

    # ── build_workflow ─────────────────────────────────────────────────────────

    def _build_workflow(
        self,
        workflow_type: str = "t2i",
        submit: bool = True,
        **kwargs,
    ) -> dict:
        """
        Build a workflow from parameters and optionally submit it.

        workflow_type:
          "t2i"   — standard text-to-image (default)
          "i2i"   — image-to-image / reinterpret
          "raw"   — kwargs["nodes"] is a list of {class_type, inputs} added in order

        submit: True = queue immediately; False = return workflow dict only.

        t2i kwargs: checkpoint, positive, negative, width, height, steps, cfg, seed,
                    sampler, scheduler, loras=[{name, weight}], filename_prefix
        i2i kwargs: same as t2i + image_path, denoise
        """
        try:
            if workflow_type == "t2i":
                workflow = WorkflowBuilder.standard_t2i(**{
                    k: v for k, v in kwargs.items() if k in (
                        "checkpoint","positive","negative","width","height",
                        "steps","cfg","seed","sampler","scheduler","loras","filename_prefix"
                    )
                })
            elif workflow_type == "i2i":
                workflow = WorkflowBuilder.img2img(**{
                    k: v for k, v in kwargs.items() if k in (
                        "checkpoint","image_path","positive","negative","denoise",
                        "steps","cfg","seed","sampler","scheduler","loras","filename_prefix"
                    )
                })
            elif workflow_type == "raw":
                b = WorkflowBuilder()
                for node in kwargs.get("nodes", []):
                    b.add(node["class_type"], node.get("inputs", {}))
                workflow = b.build()
            else:
                return {"error": f"Unknown workflow_type '{workflow_type}'. Use: t2i, i2i, raw"}
        except TypeError as e:
            return {"error": f"Bad parameters for workflow_type={workflow_type}: {e}"}

        if not submit:
            return {"ok": True, "workflow": workflow, "node_count": len(workflow)}

        return self._queue_workflow(workflow=workflow)

    # ── generate (legacy-compatible shorthand) ─────────────────────────────────

    def _generate(
        self,
        positive_prompt: str = "",
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg: float = 7.0,
        seed: int | None = None,
        model: str = "z_image_turbo_bf16.safetensors",
        loras: list[dict] | None = None,
        filename_prefix: str = "goldberg",
        **_,
    ) -> dict:
        if not positive_prompt:
            return {"error": "positive_prompt is required"}
        return self._build_workflow(
            workflow_type="t2i",
            submit=True,
            checkpoint=model,
            positive=positive_prompt,
            negative=negative_prompt,
            width=width, height=height,
            steps=steps, cfg=cfg, seed=seed,
            loras=loras or [],
            filename_prefix=filename_prefix,
        )

    # ── queue_workflow ─────────────────────────────────────────────────────────

    def _queue_workflow(self, workflow: dict, **_) -> dict:
        """Submit a pre-built workflow dict to ComfyUI /api/prompt."""
        if not workflow:
            return {"error": "workflow dict is required"}
        client_id = str(uuid.uuid4())
        try:
            r = httpx.post(
                f"{COMFYUI_BASE}/api/prompt",
                json={"prompt": workflow, "client_id": client_id},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            prompt_id = data.get("prompt_id")
            logger.info(f"[comfyui] queued prompt_id={prompt_id}")
            return {
                "ok": True, "prompt_id": prompt_id, "client_id": client_id,
                "node_count": len(workflow),
                "message": "Queued. Check status with action=status or retrieve with action=history.",
            }
        except httpx.ConnectError:
            return {"ok": False, "error": f"ComfyUI not running at {COMFYUI_BASE}. Start ComfyUI first."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── describe ──────────────────────────────────────────────────────────────

    def _describe(self, workflow: dict | None = None, **_) -> dict:
        """
        Parse a ComfyUI API-format workflow and return a human-readable breakdown.

        Identifies: checkpoints, LoRAs, samplers, prompts, dimensions — and lists
        every node with its type, literal inputs, and linked inputs annotated with
        semantic slot names where known.
        """
        if not workflow:
            return {"error": "workflow dict is required"}

        lines = []
        checkpoints, loras, samplers, prompts = [], [], [], []

        for node_id in sorted(workflow, key=lambda x: int(x) if x.isdigit() else 9999):
            node = workflow[node_id]
            ct     = node.get("class_type", "?")
            inputs = node.get("inputs", {})

            literals = {}
            linked   = {}
            for k, v in inputs.items():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[1], int):
                    src_id, slot = v
                    slot_names = _NODE_OUTPUTS.get(workflow.get(src_id, {}).get("class_type", ""), [])
                    slot_label = slot_names[slot] if slot < len(slot_names) else str(slot)
                    linked[k] = f"node {src_id}.{slot_label}"
                else:
                    literals[k] = v

            line = f"[{node_id}] {ct}"
            if literals:
                line += "\n     values: " + ", ".join(f"{k}={repr(v)}" for k, v in literals.items())
            if linked:
                line += "\n     links:  " + ", ".join(f"{k}←{v}" for k, v in linked.items())
            lines.append(line)

            # Categorize
            if ct in ("CheckpointLoaderSimple", "CheckpointLoader"):
                checkpoints.append(f"[{node_id}] {literals.get('ckpt_name', '?')}")
            elif ct == "LoraLoader":
                checkpoints_append_lora = f"[{node_id}] {literals.get('lora_name', '?')} strength={literals.get('strength_model', '?')}"
                loras.append(checkpoints_append_lora)
            elif ct in ("KSampler", "KSamplerAdvanced"):
                samplers.append(
                    f"[{node_id}] {literals.get('sampler_name','?')} steps={literals.get('steps','?')} "
                    f"cfg={literals.get('cfg','?')} seed={literals.get('seed','?')} denoise={literals.get('denoise','?')}"
                )
            elif ct == "CLIPTextEncode":
                txt = literals.get("text", "")
                prompts.append(f"[{node_id}] {txt[:80]}{'…' if len(txt) > 80 else ''}")
            elif ct == "EmptyLatentImage":
                w, h = literals.get("width", "?"), literals.get("height", "?")
                lines[-1] += f"  → {w}×{h}"

        return {
            "ok":         True,
            "node_count": len(workflow),
            "checkpoints": checkpoints,
            "loras":        loras,
            "samplers":     samplers,
            "prompts":      prompts,
            "full_graph":   "\n".join(lines),
        }

    # ── status / history / health ──────────────────────────────────────────────

    def _health(self) -> dict:
        try:
            r = httpx.get(f"{COMFYUI_BASE}/system_stats", timeout=5.0)
            r.raise_for_status()
            return {"ok": True, "comfyui": "running", "stats": r.json()}
        except Exception as e:
            return {"ok": False, "error": f"ComfyUI not reachable at {COMFYUI_BASE}: {e}"}

    def _status(self) -> dict:
        try:
            r = httpx.get(f"{COMFYUI_BASE}/queue", timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            return {
                "ok": True,
                "queue_pending": len(data.get("queue_pending", [])),
                "queue_running": len(data.get("queue_running", [])),
                "details": data,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _history(self, limit: int = 10) -> dict:
        try:
            r = httpx.get(f"{COMFYUI_BASE}/history", timeout=TIMEOUT)
            r.raise_for_status()
            history = r.json()
            items = []
            for prompt_id, entry in list(history.items())[-limit:]:
                files = [
                    img.get("filename", "?")
                    for node_out in entry.get("outputs", {}).values()
                    for img in node_out.get("images", [])
                ]
                items.append({
                    "prompt_id": prompt_id,
                    "status":    entry.get("status", {}).get("status_str", "unknown"),
                    "files":     files,
                })
            return {"ok": True, "count": len(items), "history": items}
        except Exception as e:
            return {"ok": False, "error": str(e)}
