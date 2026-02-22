# RunPod Module

Intelligent burst GPU routing for Engineer0. Automatically routes AI tasks between your local Ollama instance (free, instant) and RunPod serverless GPU cloud (powerful, pay-per-second).

## What It Does

Instead of running every AI task locally on limited hardware, this module makes routing decisions:

- **Short text, quick tasks** → local Ollama (no cost, no latency)
- **Image generation** → RunPod SDXL (requires GPU)
- **Audio transcription** → RunPod Whisper Large v3
- **Long/complex prompts** → RunPod Llama 3 70B
- **ComfyUI workflows** → RunPod ComfyUI
- **Model fine-tuning** → RunPod training endpoint

If RunPod fails or is not configured, the router falls back to local Ollama automatically.

## Setup

### 1. Install the RunPod SDK

```bash
pip install runpod>=1.6.0
```

Or install this module directly:

```bash
pip install -e ~/ai/GENESIS/runpod_module/
```

### 2. Get a RunPod API Key

1. Create an account at [runpod.io](https://runpod.io)
2. Go to Settings > API Keys
3. Generate a new key (starts with `rp_`)

RunPod is serverless — **you only pay when jobs actually run**. No idle charges.

### 3. Set Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```env
RUNPOD_API_KEY=rp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RUNPOD_ENDPOINT_SDXL=abc123xyz
RUNPOD_ENDPOINT_WHISPER=def456uvw
RUNPOD_ENDPOINT_LLAMA70B=ghi789rst
RUNPOD_ENDPOINT_COMFYUI=jkl012mno
RUNPOD_ENDPOINT_TRAINING=pqr345stu
```

You only need to set endpoint IDs for the capabilities you plan to use.

## Quick Start

### Image Generation

```python
from runpod_module import RunPodRouter

router = RunPodRouter()  # reads RUNPOD_API_KEY from env

result = router.route_image_gen(
    prompt="a cat on mars, photorealistic, 8k",
    negative_prompt="blurry, low quality",
    width=1024,
    height=1024,
)

if result["success"]:
    print(result["output"])  # URL or base64 image data
```

### Audio Transcription

```python
result = router.route_transcription(
    audio_url="https://example.com/meeting.mp3",
    language="en",
)

if result["success"]:
    print(result["output"]["text"])
```

### Heavy LLM (Auto-Routed)

```python
# Short prompt -> uses local Ollama
result = router.route_heavy_llm("What is 2+2?")
print(result["source"])  # "local_ollama"

# Long prompt -> uses RunPod Llama 70B
result = router.route_heavy_llm("Analyze this 50-page document..." * 100)
print(result["source"])  # "runpod_70b"
```

### Wire In Your Local Ollama

```python
import ollama

def local_chat(prompt: str) -> str:
    response = ollama.chat(model="llama3", messages=[{"role": "user", "content": prompt}])
    return response["message"]["content"]

router = RunPodRouter(local_chat_fn=local_chat)
```

### Generic Task Routing

```python
# Route by task type string
result = router.route_task("image", prompt="sunset over mountains")
result = router.route_task("transcribe", audio_url="https://example.com/audio.mp3")
result = router.route_task("llm", prompt="Explain quantum entanglement")

# Route directly to any RunPod endpoint by name
result = router.route_task("comfyui", workflow={...})
```

### Direct Worker Access

```python
from runpod_module import RunPodWorker

worker = RunPodWorker()

# Run any preset endpoint
result = worker.run("stable_diffusion", {"prompt": "forest in fog"})

# Run a raw endpoint ID
result = worker.run("abc123endpoint", {"input": "data"}, timeout=600)

# Fire-and-forget (returns job_id immediately)
result = worker.run("custom_training", {"dataset_url": "..."}, poll=False)
job_id = result["job_id"]

# Check status
print(worker.get_status())
print(worker.list_endpoints())
```

## Endpoint Configuration

Each preset endpoint reads its ID from an environment variable:

| Preset Name       | Env Variable               | Description                    |
|-------------------|----------------------------|--------------------------------|
| `stable_diffusion`| `RUNPOD_ENDPOINT_SDXL`     | Stable Diffusion XL image gen  |
| `whisper`         | `RUNPOD_ENDPOINT_WHISPER`  | Whisper Large v3 transcription |
| `llama70b`        | `RUNPOD_ENDPOINT_LLAMA70B` | Llama 3 70B language model     |
| `comfyui`         | `RUNPOD_ENDPOINT_COMFYUI`  | ComfyUI workflow runner        |
| `custom_training` | `RUNPOD_ENDPOINT_TRAINING` | LoRA / fine-tuning jobs        |

To get endpoint IDs, deploy a serverless endpoint from the RunPod console or use a community template. The endpoint ID appears in the endpoint's URL.

## Router Decision Logic

```
Incoming task
     |
     +-- Image / Audio / ComfyUI / Training?
     |        -> Always RunPod (no local equivalent)
     |
     +-- LLM request?
              |
              +-- prompt < 2000 chars AND local_chat_fn configured?
              |        -> Local Ollama (free, fast)
              |        -> On failure: fall back to RunPod
              |
              +-- prompt >= 2000 chars OR no local LLM?
                       -> RunPod Llama 70B
                       -> On failure: fall back to local Ollama
```

The 2000-character threshold is configurable:

```python
router.HEAVY_LLM_THRESHOLD = 4000  # chars
```

## Status Check

```python
import json
print(json.dumps(router.get_status(), indent=2))
```

```json
{
  "worker": {
    "configured": true,
    "api_key": "rp_xxxxx...",
    "endpoints": [
      {"name": "stable_diffusion", "configured": true, "endpoint_id": "abc123x..."},
      {"name": "whisper", "configured": false, "endpoint_id": "not set"}
    ]
  },
  "local_llm": "configured",
  "heavy_llm_threshold_chars": 2000
}
```

## Cost Notes

RunPod serverless billing is per-second of GPU time:

- SDXL image generation: ~$0.002–0.005 per image
- Whisper transcription: ~$0.001–0.003 per minute of audio
- Llama 70B inference: ~$0.001–0.004 per request
- No charges when endpoints are idle

Set spending limits in the RunPod dashboard to avoid surprises.
