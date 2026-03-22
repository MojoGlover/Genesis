"""
ComfyUI Data Types — the "wires" between nodes.
Each output slot has a type. Connections only work if types match.
Adams uses this to validate workflow connections.
"""

# Core ComfyUI data types and what they carry
DATA_TYPES = {
    "MODEL": {
        "description": "A loaded diffusion model (unet/checkpoint)",
        "produced_by": ["CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader",
                        "LoraLoader", "ModelMergeSimple"],
        "consumed_by": ["KSampler", "KSamplerAdvanced", "LoraLoader",
                        "IPAdapterApply", "ControlNetApply"],
    },
    "CLIP": {
        "description": "Text encoder (CLIP or T5)",
        "produced_by": ["CheckpointLoaderSimple", "CLIPLoader", "DualCLIPLoader", "LoraLoader"],
        "consumed_by": ["CLIPTextEncode", "LoraLoader", "CLIPSetLastLayer"],
    },
    "VAE": {
        "description": "Variational autoencoder — encodes/decodes latents to pixels",
        "produced_by": ["CheckpointLoaderSimple", "VAELoader"],
        "consumed_by": ["VAEEncode", "VAEDecode", "VAEEncodeForInpaint"],
    },
    "CONDITIONING": {
        "description": "Encoded text prompt or control signal",
        "produced_by": ["CLIPTextEncode", "ControlNetApply", "IPAdapterApply",
                        "ConditioningCombine", "ConditioningAverage"],
        "consumed_by": ["KSampler", "KSamplerAdvanced", "ConditioningCombine",
                        "ConditioningAverage", "ControlNetApply"],
    },
    "LATENT": {
        "description": "Image in latent space (compressed representation)",
        "produced_by": ["VAEEncode", "KSampler", "EmptyLatentImage",
                        "EmptySD3LatentImage", "LatentUpscale"],
        "consumed_by": ["KSampler", "KSamplerAdvanced", "VAEDecode",
                        "LatentUpscale", "LatentComposite"],
    },
    "IMAGE": {
        "description": "Pixel-space image tensor [B, H, W, C]",
        "produced_by": ["VAEDecode", "LoadImage", "ImageScale", "ImageUpscaleWithModel",
                        "PreviewImage", "SaveImage"],
        "consumed_by": ["VAEEncode", "LoadImage", "ControlNetApply", "ImageScale",
                        "PreviewImage", "SaveImage", "IPAdapterApply"],
    },
    "MASK": {
        "description": "Binary mask for inpainting or compositing",
        "produced_by": ["LoadImageMask", "ImageToMask", "MaskComposite"],
        "consumed_by": ["VAEEncodeForInpaint", "LatentComposite", "MaskComposite",
                        "SetLatentNoiseMask"],
    },
    "CONTROL_NET": {
        "description": "Loaded ControlNet model",
        "produced_by": ["ControlNetLoader"],
        "consumed_by": ["ControlNetApply", "ControlNetApplyAdvanced"],
    },
    "UPSCALE_MODEL": {
        "description": "Loaded upscale model (ESRGAN, etc.)",
        "produced_by": ["UpscaleModelLoader"],
        "consumed_by": ["ImageUpscaleWithModel"],
    },
    "CLIP_VISION": {
        "description": "CLIP vision encoder for image conditioning",
        "produced_by": ["CLIPVisionLoader"],
        "consumed_by": ["CLIPVisionEncode", "IPAdapterApply"],
    },
    "CLIP_VISION_OUTPUT": {
        "description": "Encoded image features from CLIP vision",
        "produced_by": ["CLIPVisionEncode"],
        "consumed_by": ["IPAdapterApply", "unCLIPConditioning"],
    },
    "SIGMAS": {
        "description": "Noise schedule sigmas for advanced sampling",
        "produced_by": ["BasicScheduler", "KarrasScheduler", "ExponentialScheduler",
                        "PolyexponentialScheduler", "SDTurboScheduler"],
        "consumed_by": ["SamplerCustom", "SamplerCustomAdvanced"],
    },
    "SAMPLER": {
        "description": "Sampler object for custom sampling",
        "produced_by": ["KSamplerSelect"],
        "consumed_by": ["SamplerCustom", "SamplerCustomAdvanced"],
    },
    "GUIDER": {
        "description": "Guidance object (CFG, DualCFG, etc.)",
        "produced_by": ["CFGGuider", "DualCFGGuider", "BasicGuider"],
        "consumed_by": ["SamplerCustomAdvanced"],
    },
    "NOISE": {
        "description": "Noise generator",
        "produced_by": ["RandomNoise", "DisableNoise"],
        "consumed_by": ["SamplerCustomAdvanced"],
    },
}

# Type compatibility — can these two types connect?
def types_compatible(output_type: str, input_type: str) -> bool:
    """Returns True if output_type can connect to input_type."""
    if output_type == input_type:
        return True
    # Special cases
    compatible_pairs = {
        ("MODEL", "MODEL"),
        ("CLIP", "CLIP"),
    }
    return (output_type, input_type) in compatible_pairs
