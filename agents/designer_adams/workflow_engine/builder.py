"""
Designer Adams — Workflow Builder
Generates ComfyUI workflow JSON from high-level specs.
Knows the standard pipeline patterns for each model family.
"""
import json
from pathlib import Path
from typing import Optional
import sys
sys.path.insert(0, '/Users/darnieglover/ai/GENESIS/agents/designer_adams')
from node_library.core_nodes import SAMPLER_RECOMMENDATIONS


class WorkflowBuilder:
    """
    Builds ComfyUI API-format workflow JSON.
    Nodes are numbered sequentially. Connections use [node_id, output_slot].
    """

    def __init__(self):
        self._nodes = {}
        self._counter = 1

    def _add(self, class_type: str, inputs: dict, title: Optional[str] = None) -> str:
        node_id = str(self._counter)
        self._counter += 1
        self._nodes[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
            "_meta": {"title": title or class_type}
        }
        return node_id

    def _ref(self, node_id: str, slot: int = 0) -> list:
        return [node_id, slot]

    def build(self) -> dict:
        return dict(self._nodes)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.build(), f, indent=2)
        return path

    # ── HIGH-LEVEL BUILDERS ───────────────────────────────────────────────────

    def flux_txt2img(
        self,
        positive_prompt: str = "a beautiful landscape, masterpiece",
        negative_prompt: str = "",
        checkpoint: str = "flux1-dev-fp8.safetensors",
        clip1: str = "t5xxl_fp8_e4m3fn.safetensors",
        clip2: str = "clip_l.safetensors",
        vae: str = "ae.safetensors",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg: float = 1.0,
        seed: int = 42,
        output_prefix: str = "flux/txt2img",
    ) -> dict:
        """Standard Flux.1 dev text-to-image workflow."""
        b = WorkflowBuilder()
        rec = SAMPLER_RECOMMENDATIONS["flux"]

        # Loaders
        unet_id = b._add("UNETLoader", {
            "unet_name": checkpoint,
            "weight_dtype": "fp8_e4m3fn"
        }, "Load Flux UNet")

        clip_id = b._add("DualCLIPLoader", {
            "clip_name1": clip1,
            "clip_name2": clip2,
            "type": "flux"
        }, "Load Flux CLIP")

        vae_id = b._add("VAELoader", {
            "vae_name": vae
        }, "Load VAE")

        # Conditioning
        pos_id = b._add("CLIPTextEncode", {
            "clip": b._ref(clip_id, 0),
            "text": positive_prompt
        }, "Positive Prompt")

        neg_id = b._add("CLIPTextEncode", {
            "clip": b._ref(clip_id, 0),
            "text": negative_prompt
        }, "Negative Prompt")

        # Latent
        latent_id = b._add("EmptySD3LatentImage", {
            "width": width,
            "height": height,
            "batch_size": 1
        }, "Empty Latent")

        # Sampling
        sampler_id = b._add("KSampler", {
            "model": b._ref(unet_id, 0),
            "positive": b._ref(pos_id, 0),
            "negative": b._ref(neg_id, 0),
            "latent_image": b._ref(latent_id, 0),
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": rec["sampler"],
            "scheduler": rec["scheduler"],
            "denoise": 1.0
        }, "KSampler")

        # Decode + Save
        decode_id = b._add("VAEDecode", {
            "samples": b._ref(sampler_id, 0),
            "vae": b._ref(vae_id, 0)
        }, "VAE Decode")

        b._add("SaveImage", {
            "images": b._ref(decode_id, 0),
            "filename_prefix": output_prefix
        }, "Save Image")

        return b.build()

    def sdxl_txt2img(
        self,
        positive_prompt: str = "a beautiful landscape, masterpiece",
        negative_prompt: str = "ugly, blurry, watermark",
        checkpoint: str = "sd_xl_base_1.0.safetensors",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg: float = 7.0,
        seed: int = 42,
        output_prefix: str = "sdxl/txt2img",
        loras: Optional[list[dict]] = None,
    ) -> dict:
        """
        Standard SDXL text-to-image workflow.
        loras: [{"name": "style.safetensors", "strength_model": 0.8, "strength_clip": 0.8}]
        """
        b = WorkflowBuilder()
        rec = SAMPLER_RECOMMENDATIONS["sdxl"]

        # Checkpoint
        ckpt_id = b._add("CheckpointLoaderSimple", {
            "ckpt_name": checkpoint
        }, "Load Checkpoint")

        model_ref = b._ref(ckpt_id, 0)
        clip_ref = b._ref(ckpt_id, 1)
        vae_ref = b._ref(ckpt_id, 2)

        # LoRA chain
        if loras:
            for lora in loras:
                lora_id = b._add("LoraLoader", {
                    "model": model_ref,
                    "clip": clip_ref,
                    "lora_name": lora["name"],
                    "strength_model": lora.get("strength_model", 0.8),
                    "strength_clip": lora.get("strength_clip", 0.8),
                }, f"LoRA: {lora['name']}")
                model_ref = b._ref(lora_id, 0)
                clip_ref = b._ref(lora_id, 1)

        # Conditioning
        pos_id = b._add("CLIPTextEncode", {
            "clip": clip_ref,
            "text": positive_prompt
        }, "Positive Prompt")

        neg_id = b._add("CLIPTextEncode", {
            "clip": clip_ref,
            "text": negative_prompt
        }, "Negative Prompt")

        # Latent
        latent_id = b._add("EmptyLatentImage", {
            "width": width,
            "height": height,
            "batch_size": 1
        }, "Empty Latent")

        # Sampling
        sampler_id = b._add("KSampler", {
            "model": model_ref,
            "positive": b._ref(pos_id, 0),
            "negative": b._ref(neg_id, 0),
            "latent_image": b._ref(latent_id, 0),
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": rec["sampler"],
            "scheduler": rec["scheduler"],
            "denoise": 1.0
        }, "KSampler")

        # Decode + Save
        decode_id = b._add("VAEDecode", {
            "samples": b._ref(sampler_id, 0),
            "vae": vae_ref
        }, "VAE Decode")

        b._add("SaveImage", {
            "images": b._ref(decode_id, 0),
            "filename_prefix": output_prefix
        }, "Save Image")

        return b.build()

    def sdxl_img2img(
        self,
        positive_prompt: str,
        negative_prompt: str = "ugly, blurry",
        checkpoint: str = "sd_xl_base_1.0.safetensors",
        input_image_path: str = "/input/image.png",
        denoise: float = 0.65,
        steps: int = 25,
        cfg: float = 7.0,
        seed: int = 42,
        output_prefix: str = "sdxl/img2img",
    ) -> dict:
        """SDXL img2img workflow."""
        b = WorkflowBuilder()
        rec = SAMPLER_RECOMMENDATIONS["sdxl"]

        ckpt_id = b._add("CheckpointLoaderSimple", {"ckpt_name": checkpoint}, "Load Checkpoint")

        load_img_id = b._add("LoadImage", {
            "image": input_image_path,
            "upload": "image"
        }, "Load Input Image")

        pos_id = b._add("CLIPTextEncode", {
            "clip": b._ref(ckpt_id, 1),
            "text": positive_prompt
        }, "Positive Prompt")

        neg_id = b._add("CLIPTextEncode", {
            "clip": b._ref(ckpt_id, 1),
            "text": negative_prompt
        }, "Negative Prompt")

        encode_id = b._add("VAEEncode", {
            "pixels": b._ref(load_img_id, 0),
            "vae": b._ref(ckpt_id, 2)
        }, "Encode Image to Latent")

        sampler_id = b._add("KSampler", {
            "model": b._ref(ckpt_id, 0),
            "positive": b._ref(pos_id, 0),
            "negative": b._ref(neg_id, 0),
            "latent_image": b._ref(encode_id, 0),
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": rec["sampler"],
            "scheduler": rec["scheduler"],
            "denoise": denoise
        }, "KSampler")

        decode_id = b._add("VAEDecode", {
            "samples": b._ref(sampler_id, 0),
            "vae": b._ref(ckpt_id, 2)
        }, "VAE Decode")

        b._add("SaveImage", {
            "images": b._ref(decode_id, 0),
            "filename_prefix": output_prefix
        }, "Save Image")

        return b.build()
