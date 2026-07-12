# ComfyUI Workflow Building Guide — Goldberg Reference

## What is the ComfyUI API format?

ComfyUI workflows are submitted as a flat dict where each key is a string node ID
and each value describes one node.

```json
{
  "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
  "2": {"class_type": "CLIPTextEncode",         "inputs": {"text": "a cat", "clip": ["1", 1]}},
  ...
}
```

**Links** are arrays: `["src_node_id", output_slot_index]`  
`["1", 1]` = output slot 1 of node "1" = the CLIP tensor from CheckpointLoaderSimple

**Literals** are plain values: strings, ints, floats, booleans.

---

## Output slot reference

| Node class               | Slot 0    | Slot 1  | Slot 2 |
|--------------------------|-----------|---------|--------|
| CheckpointLoaderSimple   | MODEL     | CLIP    | VAE    |
| CheckpointLoader         | MODEL     | CLIP    | VAE    |
| LoraLoader               | MODEL     | CLIP    |        |
| CLIPTextEncode           | CONDITIONING |      |        |
| EmptyLatentImage         | LATENT    |         |        |
| KSampler                 | LATENT    |         |        |
| KSamplerAdvanced         | LATENT    |         |        |
| VAEDecode                | IMAGE     |         |        |
| VAEEncode                | LATENT    |         |        |
| ImageScale               | IMAGE     |         |        |
| UpscaleModelLoader       | UPSCALE_MODEL |      |        |
| ImageUpscaleWithModel    | IMAGE     |         |        |
| LoadImage                | IMAGE     | MASK    |        |
| ControlNetLoader         | CONTROL_NET |        |        |
| ControlNetApplyAdvanced  | POSITIVE  | NEGATIVE |       |

---

## Standard text-to-image workflow (with LoRA chain)

Node order and wiring:

```
CheckpointLoaderSimple(ckpt_name)
  → LoraLoader(model=ckpt.MODEL, clip=ckpt.CLIP, lora_name, strength_model, strength_clip)
  → LoraLoader(model=lora1.MODEL, clip=lora1.CLIP, ...)   # chain as many as needed
  → EmptyLatentImage(width, height, batch_size=1)
  → CLIPTextEncode(text=positive, clip=lastLora.CLIP)
  → CLIPTextEncode(text=negative, clip=lastLora.CLIP)
  → KSampler(model=lastLora.MODEL, positive=pos.CONDITIONING, negative=neg.CONDITIONING,
             latent_image=empty.LATENT, seed, steps, cfg, sampler_name, scheduler, denoise=1.0)
  → VAEDecode(samples=ksampler.LATENT, vae=ckpt.VAE)
  → SaveImage(images=vae.IMAGE, filename_prefix="goldberg")
```

LoRA chaining rule: each LoraLoader takes the MODEL and CLIP from the previous node
(either the checkpoint or the previous LoraLoader) and outputs a new MODEL and CLIP.
The final MODEL and CLIP flow into the KSampler and CLIPTextEncode respectively.

---

## Image-to-image (reinterpret) workflow

Same as t2i but replace EmptyLatentImage with LoadImage → VAEEncode:

```
CheckpointLoaderSimple → (optional LoRA chain) → ...
LoadImage(image="path/to/image.png")
  → VAEEncode(pixels=load.IMAGE, vae=ckpt.VAE)
  → KSampler(..., latent_image=vaeEncode.LATENT, denoise=0.6)
  → VAEDecode → SaveImage
```

`denoise` controls how much the original image is preserved:
- 0.3–0.5 = subtle variation, keeps composition
- 0.6–0.75 = noticeable reinterpretation
- 0.9–1.0 = near-full regeneration

---

## Sampler reference

| sampler_name    | Best for                                  |
|-----------------|-------------------------------------------|
| euler           | Fast, creative, slight noise              |
| euler_ancestral | More variation, unpredictable             |
| dpmpp_2m        | Sharp, detailed — default for SDXL        |
| dpmpp_sde       | Soft, painterly quality                   |
| ddim            | Deterministic, good for img2img           |
| uni_pc          | Fast + clean                              |

| scheduler  | Effect                              |
|------------|-------------------------------------|
| karras     | Smooth noise schedule, most popular |
| normal     | Standard cosine                     |
| exponential| Aggressive early denoising          |

CFG scale:
- 4–6: loose, creative, less literal
- 7–8: balanced (default)
- 9–12: very literal, can look over-cooked at high values
- Flux models: 1–3.5 (much lower)

---

## Using the describe action to learn from a workflow

When you receive a workflow dict (e.g., from Atelier's reinterpret feature):

```
{action: "describe", workflow: <the workflow dict>}
```

Returns:
- `checkpoints`: which model was loaded
- `loras`: each LoRA name and strength
- `samplers`: sampler, steps, cfg, seed, denoise
- `prompts`: positive and negative text
- `full_graph`: every node annotated with types, values, and link labels

Use this to understand what settings produced a result, then reproduce or vary them.

---

## Using build_workflow to generate

Text-to-image with LoRAs:
```
{
  action: "build_workflow",
  workflow_type: "t2i",
  checkpoint: "NoobAI-XL-v-pred.safetensors",
  positive: "cinematic portrait, dramatic rim lighting, dark background, 8k uhd",
  negative: "blurry, low quality, bad anatomy, watermark",
  width: 1024, height: 1024,
  steps: 28, cfg: 6.5,
  loras: [{"name": "detail_tweaker_xl.safetensors", "weight": 0.7}],
  filename_prefix: "goldberg_portrait",
  submit: true
}
```

Img2img reinterpretation:
```
{
  action: "build_workflow",
  workflow_type: "i2i",
  checkpoint: "NoobAI-XL-v-pred.safetensors",
  image_path: "ComfyUI/input/reference.png",
  positive: "same scene, watercolor painting style, soft pastels",
  denoise: 0.7,
  steps: 20, cfg: 7.0,
  submit: true
}
```

Check what's available before building:
```
{action: "health"}              — is ComfyUI running?
{action: "status"}              — queue depth
{action: "history", limit: 5}  — recent outputs
```

---

## How to read a workflow that came from Atelier

When Atelier sends a reinterpret workflow to ComfyUI via the bridge, the same dict
is available via `/api/reinterpret-workflow`. Use the describe action on that dict.

Pattern for learning from a reference image's workflow:
1. User clicks "Open in ComfyUI" from Atelier discover panel
2. Atelier posts the workflow to ComfyUI (node graph appears in editor)
3. Goldberg can describe that workflow to understand the node chain
4. Goldberg can then build_workflow with similar or modified parameters

---

## Available local models (as of 2026-06)

Checkpoints (on Z Slim or local_models):
- NoobAI-XL-v-pred.safetensors      (SDXL, anime/illustration)
- RealisticVision (SD1.5, photorealistic)
- flux1-schnell-fp8.safetensors     (Flux Schnell, fast)
- z_image_turbo_bf16.safetensors    (fast turbo variant)

Use `{action: "health"}` to confirm ComfyUI is running, then check loaded models
via the ComfyUI /object_info endpoint if uncertain about exact filenames.
