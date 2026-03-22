"""
Core ComfyUI node catalog.
Each entry defines: inputs, outputs, description, common mistakes, tips.
Adams uses this to explain nodes and validate workflows.
"""

CORE_NODES = {

    # ── LOADERS ──────────────────────────────────────────────────────────────

    "CheckpointLoaderSimple": {
        "category": "loaders",
        "description": "Loads a full checkpoint model (unet + CLIP + VAE in one file). Standard for SDXL, Pony, Illustrious.",
        "inputs": {"ckpt_name": "STRING"},
        "outputs": ["MODEL", "CLIP", "VAE"],
        "tips": "Use for merged checkpoints (.safetensors). Not for Flux — Flux uses separate unet + text encoders.",
        "common_mistakes": ["Loading a Flux model here — it won't work, use UNETLoader instead"],
    },

    "UNETLoader": {
        "category": "loaders",
        "description": "Loads a standalone diffusion model (unet only). Required for Flux.1 dev/schnell.",
        "inputs": {"unet_name": "STRING", "weight_dtype": "STRING"},
        "outputs": ["MODEL"],
        "tips": "For Flux: set weight_dtype to 'fp8_e4m3fn' for VRAM savings on the unet.",
        "common_mistakes": ["Forgetting to also load CLIP and VAE separately when using UNETLoader"],
    },

    "DualCLIPLoader": {
        "category": "loaders",
        "description": "Loads two CLIP models simultaneously. Required for Flux (needs T5-XXL + CLIP-L).",
        "inputs": {"clip_name1": "STRING", "clip_name2": "STRING", "type": "STRING"},
        "outputs": ["CLIP"],
        "tips": "For Flux: clip_name1=t5xxl_fp8_e4m3fn.safetensors, clip_name2=clip_l.safetensors, type=flux",
        "common_mistakes": ["Using CLIPLoader instead of DualCLIPLoader for Flux — will fail"],
    },

    "VAELoader": {
        "category": "loaders",
        "description": "Loads a standalone VAE. Use when checkpoint has baked-in poor VAE or for Flux.",
        "inputs": {"vae_name": "STRING"},
        "outputs": ["VAE"],
        "tips": "For Flux: ae.safetensors. For SDXL: sdxl_vae.safetensors or leave in checkpoint.",
        "common_mistakes": [],
    },

    "LoraLoader": {
        "category": "loaders",
        "description": "Applies a LoRA to the model and/or CLIP. Can be chained for multiple LoRAs.",
        "inputs": {"model": "MODEL", "clip": "CLIP", "lora_name": "STRING",
                   "strength_model": "FLOAT", "strength_clip": "FLOAT"},
        "outputs": ["MODEL", "CLIP"],
        "tips": "Chain multiple LoraLoader nodes for stacking. strength_model 0.6-0.9 typical. Set strength_clip to 0 if LoRA is model-only.",
        "common_mistakes": [
            "Setting strength too high (>1.2) — causes artifacts",
            "Stacking too many LoRAs without lowering individual strengths",
            "Using an SDXL LoRA on a Flux model — architectures are incompatible",
        ],
    },

    "ControlNetLoader": {
        "category": "loaders",
        "description": "Loads a ControlNet model.",
        "inputs": {"control_net_name": "STRING"},
        "outputs": ["CONTROL_NET"],
        "tips": "Match ControlNet to your base model — SDXL ControlNets won't work with SD1.5 and vice versa.",
        "common_mistakes": ["Using a SD1.5 ControlNet with SDXL checkpoint"],
    },

    # ── TEXT ENCODING ─────────────────────────────────────────────────────────

    "CLIPTextEncode": {
        "category": "conditioning",
        "description": "Encodes a text prompt into conditioning using the CLIP model.",
        "inputs": {"clip": "CLIP", "text": "STRING"},
        "outputs": ["CONDITIONING"],
        "tips": "Use two — one for positive, one for negative prompt. Both feed into KSampler.",
        "common_mistakes": ["Connecting same conditioning to both positive and negative inputs"],
    },

    # ── SAMPLING ──────────────────────────────────────────────────────────────

    "KSampler": {
        "category": "sampling",
        "description": "The main sampler. Denoises a latent using the model and conditioning.",
        "inputs": {
            "model": "MODEL", "positive": "CONDITIONING", "negative": "CONDITIONING",
            "latent_image": "LATENT", "seed": "INT", "steps": "INT",
            "cfg": "FLOAT", "sampler_name": "STRING", "scheduler": "STRING",
            "denoise": "FLOAT"
        },
        "outputs": ["LATENT"],
        "tips": (
            "SDXL: 20-30 steps, cfg 7-9, euler/dpmpp_2m + karras. "
            "Flux: 20-28 steps, cfg 1.0 (Flux ignores CFG), euler + simple. "
            "denoise=1.0 for txt2img, 0.5-0.8 for img2img."
        ),
        "common_mistakes": [
            "Using CFG > 3 with Flux — has no effect, wastes compute",
            "Using karras scheduler with Flux — use 'simple' or 'beta'",
            "Steps below 15 — usually too few for quality",
        ],
    },

    "KSamplerAdvanced": {
        "category": "sampling",
        "description": "Extended KSampler with start/end step control. Used in hires-fix and refiner workflows.",
        "inputs": {
            "model": "MODEL", "positive": "CONDITIONING", "negative": "CONDITIONING",
            "latent_image": "LATENT", "noise_seed": "INT", "steps": "INT",
            "cfg": "FLOAT", "sampler_name": "STRING", "scheduler": "STRING",
            "start_at_step": "INT", "end_at_step": "INT", "add_noise": "BOOLEAN",
            "return_with_leftover_noise": "BOOLEAN"
        },
        "outputs": ["LATENT"],
        "tips": "For SDXL refiner: base runs 0→20 steps, refiner runs 20→25. Set end_at_step on base, start_at_step on refiner.",
        "common_mistakes": ["Setting end_at_step higher than total steps"],
    },

    # ── LATENT ────────────────────────────────────────────────────────────────

    "EmptyLatentImage": {
        "category": "latent",
        "description": "Creates a blank latent image of given dimensions.",
        "inputs": {"width": "INT", "height": "INT", "batch_size": "INT"},
        "outputs": ["LATENT"],
        "tips": "SDXL native: 1024x1024, 1216x832, 832x1216. SD1.5: 512x512 or 768x768. Flux: 1024x1024 recommended.",
        "common_mistakes": [
            "Using non-standard dimensions — SDXL trained on specific aspect ratios",
            "Using SD1.5 dimensions (512x512) with SDXL — will produce garbage",
        ],
    },

    "EmptySD3LatentImage": {
        "category": "latent",
        "description": "Creates a blank latent for SD3 and Flux models (different latent space).",
        "inputs": {"width": "INT", "height": "INT", "batch_size": "INT"},
        "outputs": ["LATENT"],
        "tips": "Use this instead of EmptyLatentImage for Flux workflows.",
        "common_mistakes": ["Using EmptyLatentImage with Flux — wrong latent scaling factor"],
    },

    # ── VAE ───────────────────────────────────────────────────────────────────

    "VAEDecode": {
        "category": "vae",
        "description": "Converts a latent image to pixel space.",
        "inputs": {"samples": "LATENT", "vae": "VAE"},
        "outputs": ["IMAGE"],
        "tips": "Always at the end of your pipeline before SaveImage or PreviewImage.",
        "common_mistakes": ["Forgetting to connect the VAE — will use a default that may mismatch"],
    },

    "VAEEncode": {
        "category": "vae",
        "description": "Converts a pixel image to latent space for img2img.",
        "inputs": {"pixels": "IMAGE", "vae": "VAE"},
        "outputs": ["LATENT"],
        "tips": "Set denoise on KSampler to 0.5-0.75 for img2img variations.",
        "common_mistakes": [],
    },

    # ── IMAGE ─────────────────────────────────────────────────────────────────

    "SaveImage": {
        "category": "image",
        "description": "Saves image to ComfyUI output folder.",
        "inputs": {"images": "IMAGE", "filename_prefix": "STRING"},
        "outputs": [],
        "tips": "Use filename_prefix with subfolders: 'flux/portrait' saves to output/flux/portrait_xxxxx.png",
        "common_mistakes": [],
    },

    "ImageScale": {
        "category": "image",
        "description": "Scales an image by target dimensions or factor.",
        "inputs": {"image": "IMAGE", "upscale_method": "STRING",
                   "width": "INT", "height": "INT", "crop": "STRING"},
        "outputs": ["IMAGE"],
        "tips": "For hires fix: scale up 1.5x then re-encode and re-sample with lower denoise.",
        "common_mistakes": [],
    },

    # ── CONTROLNET ────────────────────────────────────────────────────────────

    "ControlNetApply": {
        "category": "controlnet",
        "description": "Applies ControlNet guidance to conditioning.",
        "inputs": {"conditioning": "CONDITIONING", "control_net": "CONTROL_NET",
                   "image": "IMAGE", "strength": "FLOAT"},
        "outputs": ["CONDITIONING"],
        "tips": "Connect output to KSampler positive input. strength 0.6-1.0 typical. Lower for subtle guidance.",
        "common_mistakes": [
            "Connecting to negative conditioning — almost never what you want",
            "Not preprocessing the control image (no Canny/depth/pose preprocessor)",
        ],
    },
}

# Sampler recommendations by model family
SAMPLER_RECOMMENDATIONS = {
    "flux": {
        "sampler": "euler",
        "scheduler": "simple",
        "steps": 20,
        "cfg": 1.0,
        "note": "Flux is a guidance-distilled model. CFG has no effect. Use 'simple' or 'beta' scheduler."
    },
    "sdxl": {
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "steps": 25,
        "cfg": 7.0,
        "note": "SDXL sweet spot. euler also works well. Karras gives smooth results."
    },
    "pony": {
        "sampler": "euler_ancestral",
        "scheduler": "karras",
        "steps": 30,
        "cfg": 7.0,
        "note": "Pony responds well to ancestral samplers. Higher steps for detail."
    },
    "illustrious": {
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "steps": 28,
        "cfg": 7.0,
        "note": "Similar to SDXL base settings. Slightly higher steps for cleaner anime lines."
    },
    "sd15": {
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "steps": 20,
        "cfg": 7.0,
        "note": "Classic SD1.5 settings. Euler_a also popular for more variety."
    },
}
