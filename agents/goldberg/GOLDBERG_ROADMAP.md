# Goldberg (GBS) — Art Tools Roadmap

Agent path: GENESIS/agents/goldberg/
Port: 5006
Model: goldberg:latest (FROM blackzero-hardened:latest)
Color: #a855f7

---

## Tools to Build

### 1. civitai_tool.py ← NEXT
Fetch ComfyUI workflows and download models from CivitAI.

```
Actions:
  fetch_workflow(url)        — pull workflow JSON from a CivitAI page or shared image
  list_models(query, type)   — search CivitAI for checkpoints / LoRAs / embeddings
  download_model(model_id)   — pull model into ComfyUI models dir
  analyze_workflow(json)     — read node graph, list what models/nodes are required
  deploy_workflow(json)      — POST to ComfyUI /api/prompt and run it
```

**Auth:** CivitAI API key stored in Cerberus vault (service="civitai").
Concierge handles the Discord OAuth login to retrieve the key initially.

**ComfyUI path:** ~/ai/art/ComfyUI/
**Models path:** ~/ai/art/ComfyUI/models/ (symlinked to SSD when connected)
**SSD symlink:** `ln -s /Volumes/<DriveName>/models ~/ai/art/models`

---

### 2. video_timeline.py
Python timeline model that compiles to FFmpeg filter_complex.

```python
Timeline(duration=30, tracks=[
  VideoTrack([
    Clip("bg.mp4", start=0, end=8),
    Transition("dissolve", duration=1),
    Clip("shot2.mp4", start=8, end=20),
  ]),
  OverlayTrack([
    TextOverlay("Computer Black", start=2, end=6, style="title"),
    LogoOverlay("cb_logo.png", start=0, end=30, position="bottom_right"),
  ]),
  AudioTrack("music_bed.mp3", volume=0.4),
])
```

Compiles to FFmpeg filter_complex. No GUI required. Goldberg drives it end-to-end.

---

### 3. video_assembler.py
Takes a Timeline, runs FFmpeg, returns output .mp4 path.

```
Actions:
  assemble(timeline)    — render to output file
  preview(timeline)     — low-res fast preview
  extract_frame(video)  — pull a still for review
  add_audio(video, audio, volume) — mix audio into existing video
```

Requires: FFmpeg installed (`brew install ffmpeg`)

---

### 4. adobe_stock_tool.py
Search and pull watermarked previews from Adobe Stock API.

```
Actions:
  search(query, filters)   — keyword search, returns preview URLs + metadata
  preview(asset_id)        — download watermarked comp image
  license(asset_id)        — license and download full-res (requires paid account)
```

**Auth:** Adobe Stock API key in Cerberus vault (service="adobe_stock").
Watermarked previews are free — good for reference and comping.

---

### 5. replicate_tool.py ← PARTIALLY BUILT
Cloud inference fallback when ComfyUI is unavailable or task is heavy.

```
Models:
  flux-schnell   — fast image gen (black-forest-labs/flux-schnell, $0.003/img)
  flux-dev       — quality image gen
  sdxl           — stable diffusion XL
  wan-video      — video generation (Wan2.1)
  cogvideox      — video generation fallback
```

**Auth:** REPLICATE_API_TOKEN env var.

---

## ComfyUI Setup

**Install location:** ~/ai/art/ComfyUI/
**Launch:** ~/ai/art/launch_comfyui.sh (MPS-accelerated, Apple Silicon)
**Port:** 8188
**Models config:** ~/ai/art/ComfyUI/extra_model_paths.yaml (already configured)

**SSD reconnect procedure:**
```bash
ln -s /Volumes/<DriveName>/models ~/ai/art/models
bash ~/ai/art/launch_comfyui.sh
```

**To start ComfyUI from Goldberg:** POST to http://127.0.0.1:8188/api/prompt

---

## Credential Chain

| Service      | Stored in Cerberus as | Retrieved by  |
|--------------|-----------------------|---------------|
| CivitAI API  | "civitai"             | Goldberg      |
| Adobe Stock  | "adobe_stock"         | Goldberg      |
| Replicate    | "replicate"           | Goldberg      |
| Discord      | "discord"             | Concierge     |
| CivitAI login| via Discord OAuth     | Concierge     |

Concierge flow:
1. Retrieve Discord creds from Cerberus
2. Navigate civitai.com → Sign in with Discord
3. Go to account → API Keys → copy key
4. Store key in Cerberus as "civitai"

---

## Vision Input (Goggles / Camera)

When hardware is ready (Android XR goggles, or phone camera now):

```
Device camera → companion app → WebSocket → PlugOps → Goldberg
```

Goldberg tools needed:
- `capture_reference(image)` — analyze palette, style, composition → save to project library
- `style_match(image, brief)` — extract visual style, use as ComfyUI reference

Janet tools needed:
- `see(image)` — contextual awareness, read text, describe scene, trigger actions

PlugOps needs:
- Vision input endpoint: POST /api/v1/vision → routes image frame to target agent

---

## Creative Studio UI (Separate App)

Not PlugOps dashboard — a dedicated creative workspace.
Connected to PlugOps via WebSocket (Goldberg is just another agent on the grid).

```
Creative Studio
  ├── Project board (briefs, status, revision history)
  ├── Asset library (generated images, downloaded stock, video clips)
  ├── Timeline editor (review Goldberg's assembled cuts)
  └── Brief composer (send to Goldberg → get back draft)
```

Architecture: separate repo, separate UI. Talks to Goldberg through PlugOps.
