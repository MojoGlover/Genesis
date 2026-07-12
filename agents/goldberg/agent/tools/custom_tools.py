"""
custom_tools.py — Goldberg's art-pipeline tools, wired through the BlackZero
custom-tools seam (agent/tools/registry.py's `_load_custom_tools()`).

Migrated 2026-07-11: Goldberg's registry.py previously hardwired these 17
tools directly into its own copy of build_executor()/TOOL_DOCS (an old,
pre-seam template generation — Engineer0-era header still in that file).
This file ports the same tools with IDENTICAL behavior and output formatting
onto the current template's seam, so Goldberg can be rebuilt from BlackZero
via build_agent.py without losing its art pipeline.

The underlying tool modules (civitai_tool.py, comfyui_tool.py, runpod_tool.py,
b2_tool.py) are unchanged — they were already self-contained (stdlib + httpx +
yaml only, no registry-specific code) and are copied alongside this file as
manifest tool_files.

RISK CARRIED FORWARD, UNCHANGED BY THIS MIGRATION (flagging, not fixing):
  - runpod_create_pod / civitai_download_model / b2_upload_file are
    cost- or irreversible-bearing (GPU billing, disk writes, cloud storage)
    and — like every tool on every BlackZero agent — currently pass through
    a policy gate that is fail-open (see BlackZero audit 2026-07-11,
    agent/modules/policy.py). No new risk here; same gap Goldberg already had.
"""
from __future__ import annotations

import json

from agent.tools import civitai_tool, comfyui_tool, runpod_tool, b2_tool


# ── CivitAI ────────────────────────────────────────────────────────────────────

def _civitai_list_models(query: str, type: str = "Checkpoint", limit: int = 10) -> str:
    result = civitai_tool.list_models(query, type=type, limit=limit)
    if not result["ok"]:
        return f"civitai_list_models failed: {result.get('error')}"
    lines = [f"Found {result['total']} models (showing {len(result['models'])}):\n"]
    for m in result["models"]:
        lines.append(
            f"  [{m['id']}] {m['name']} ({m['type']}) "
            f"↓{m['downloads']:,}  ★{m['rating']:.1f}  "
            f"version_id={m['latest_version_id']}"
        )
    return "\n".join(lines)


def _civitai_fetch_workflow(url: str) -> str:
    result = civitai_tool.fetch_workflow(url)
    if not result["ok"]:
        return f"civitai_fetch_workflow failed: {result.get('error')}"
    note = f"\nNote: {result['note']}" if result.get("note") else ""
    return f"Source: {result['source']}{note}\n{json.dumps(result['workflow'], indent=2)[:8000]}"


def _civitai_download_model(model_version_id: int, dest_name: str = "") -> str:
    result = civitai_tool.download_model(model_version_id, dest_name=dest_name)
    if not result["ok"]:
        return f"civitai_download_model failed: {result.get('error')}"
    note = f" ({result['note']})" if result.get("note") else ""
    return f"Downloaded: {result['path']} ({result['size_mb']} MB){note}"


def _civitai_analyze_workflow(workflow: dict) -> str:
    result = civitai_tool.analyze_workflow(workflow)
    if not result["ok"]:
        return f"civitai_analyze_workflow failed: {result.get('error')}"
    lines = [result["summary"]]
    if result["required_models"]:
        lines.append("\nRequired models:")
        for m in result["required_models"]:
            lines.append(f"  [{m['type']}] {m['name']}")
    return "\n".join(lines)


def _civitai_deploy_workflow(workflow: dict, client_id: str = "goldberg") -> str:
    result = civitai_tool.deploy_workflow(workflow, client_id=client_id)
    if not result["ok"]:
        return f"civitai_deploy_workflow failed: {result.get('error')}"
    return f"Queued — prompt_id: {result['prompt_id']}  position: {result['queue_position']}"


# ── ComfyUI ────────────────────────────────────────────────────────────────────

def _comfyui_queue() -> str:
    result = comfyui_tool.queue_status()
    if not result["ok"]:
        return f"comfyui_queue failed: {result.get('error')}"
    return f"ComfyUI queue — running: {result['running']}  pending: {result['pending']}"


def _comfyui_poll(prompt_id: str, timeout: int = 180) -> str:
    result = comfyui_tool.poll_result(prompt_id, timeout=timeout)
    if not result["ok"]:
        return f"comfyui_poll failed: {result.get('error')}"
    if not result["images"]:
        return "Job finished but no images in output."
    lines = [f"Done — {len(result['images'])} image(s):"]
    for img in result["images"]:
        lines.append(f"  {img['path']}")
        lines.append(f"  View: {img['view_url']}")
    return "\n".join(lines)


def _comfyui_view(prompt_id: str = "", path: str = "") -> str:
    result = comfyui_tool.view_output(prompt_id=prompt_id, path=path)
    if not result["ok"]:
        return f"comfyui_view failed: {result.get('error')}"
    note = f"\nNote: {result['note']}" if result.get("note") else ""
    return f"Opened {len(result['opened'])} image(s):\n" + "\n".join(result["opened"]) + note


def _comfyui_list_outputs(n: int = 10) -> str:
    result = comfyui_tool.list_outputs(n=n)
    if not result["ok"]:
        return f"comfyui_list_outputs failed: {result.get('error')}"
    if not result["images"]:
        return result.get("note", "No output images found.")
    lines = [f"{len(result['images'])} recent output(s):"]
    for img in result["images"]:
        lines.append(f"  {img['filename']}  {img['size_kb']}KB  {img['modified']}")
        lines.append(f"    {img['path']}")
    return "\n".join(lines)


# ── RunPod ─────────────────────────────────────────────────────────────────────

def _runpod_list_pods() -> str:
    result = runpod_tool.list_pods()
    if not result["ok"]:
        return f"runpod_list_pods failed: {result.get('error')}"
    if not result["pods"]:
        return "No RunPod pods found."
    lines = [f"{result['count']} pod(s):"]
    for p in result["pods"]:
        gpu = p.get("machine", {}).get("gpuDisplayName", "unknown GPU")
        status = p.get("desiredStatus", "?")
        cost = p.get("costPerHr", 0)
        lines.append(f"  [{p['id']}] {p['name']}  {gpu}  {status}  ${cost:.3f}/hr")
    return "\n".join(lines)


def _runpod_get_pod(pod_id: str) -> str:
    result = runpod_tool.get_pod(pod_id)
    if not result["ok"]:
        return f"runpod_get_pod failed: {result.get('error')}"
    return json.dumps(result["pod"], indent=2)


def _runpod_create_pod(
    gpu_type: str = "NVIDIA GeForce RTX 4090",
    image: str = "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
    name: str = "goldberg-pod",
    env: dict | None = None,
    disk_gb: int = 20,
    container_disk_gb: int = 20,
    ports: str = "8888/http",
) -> str:
    result = runpod_tool.create_pod(
        gpu_type=gpu_type, image=image, env=env, name=name,
        disk_gb=disk_gb, container_disk_gb=container_disk_gb, ports=ports,
    )
    if not result["ok"]:
        return f"runpod_create_pod failed: {result.get('error')}"
    p = result["pod"]
    gpu = p.get("machine", {}).get("gpuDisplayName", "unknown GPU")
    return f"Pod created — id: {p['id']}  name: {p['name']}  gpu: {gpu}  status: {p['desiredStatus']}  ${p.get('costPerHr', 0):.3f}/hr"


def _runpod_stop_pod(pod_id: str) -> str:
    result = runpod_tool.stop_pod(pod_id)
    if not result["ok"]:
        return f"runpod_stop_pod failed: {result.get('error')}"
    p = result.get("pod", {})
    return f"Pod stopped — id: {p.get('id', pod_id)}  status: {p.get('desiredStatus', 'EXITED')}"


def _runpod_terminate_pod(pod_id: str) -> str:
    result = runpod_tool.terminate_pod(pod_id)
    if not result["ok"]:
        return f"runpod_terminate_pod failed: {result.get('error')}"
    return f"Pod terminated: {result['terminated']}"


# ── Backblaze B2 ───────────────────────────────────────────────────────────────

def _b2_list_files(prefix: str = "", limit: int = 100) -> str:
    result = b2_tool.list_files(prefix=prefix, limit=limit)
    if not result["ok"]:
        return f"b2_list_files failed: {result.get('error')}"
    if not result["files"]:
        return f"No files in bucket '{result.get('bucket', '')}'."
    lines = [f"{result['count']} file(s) in {result['bucket']}:"]
    for f in result["files"]:
        lines.append(f"  {f['name']}  {f['size_kb']}KB")
    return "\n".join(lines)


def _b2_upload_file(local_path: str, dest: str = "") -> str:
    result = b2_tool.upload_file(local_path, dest=dest)
    if not result["ok"]:
        return f"b2_upload_file failed: {result.get('error')}"
    return f"Uploaded: {result['name']} ({result['size_kb']}KB) → {result['bucket']}"


def _b2_download_file(remote_name: str, dest: str = "") -> str:
    result = b2_tool.download_file(remote_name, dest=dest)
    if not result["ok"]:
        return f"b2_download_file failed: {result.get('error')}"
    return f"Downloaded: {result['name']} ({result['size_kb']}KB) → {result['path']}"


# ── Seam exports ───────────────────────────────────────────────────────────────

CUSTOM_TOOLS: dict = {
    "civitai_list_models":     _civitai_list_models,
    "civitai_fetch_workflow":  _civitai_fetch_workflow,
    "civitai_download_model":  _civitai_download_model,
    "civitai_analyze_workflow": _civitai_analyze_workflow,
    "civitai_deploy_workflow": _civitai_deploy_workflow,
    "comfyui_queue":           _comfyui_queue,
    "comfyui_poll":            _comfyui_poll,
    "comfyui_view":            _comfyui_view,
    "comfyui_list_outputs":    _comfyui_list_outputs,
    "runpod_list_pods":        _runpod_list_pods,
    "runpod_get_pod":          _runpod_get_pod,
    "runpod_create_pod":       _runpod_create_pod,
    "runpod_stop_pod":         _runpod_stop_pod,
    "runpod_terminate_pod":    _runpod_terminate_pod,
    "b2_list_files":           _b2_list_files,
    "b2_upload_file":          _b2_upload_file,
    "b2_download_file":        _b2_download_file,
}

CUSTOM_SCHEMAS: list = [
    {
        "name": "civitai_list_models",
        "description": "Search CivitAI for checkpoints, LoRAs, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (e.g. 'realistic portrait')"},
                "type":  {"type": "string", "description": "Checkpoint | LORA | TextualInversion | Controlnet | VAE | Upscaler", "default": "Checkpoint"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "civitai_fetch_workflow",
        "description": "Pull workflow JSON from a CivitAI image or model URL.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "CivitAI image or model URL"}},
            "required": ["url"],
        },
    },
    {
        "name": "civitai_download_model",
        "description": "Download a CivitAI model version into local_models/. Writes to disk — no cost gate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_version_id": {"type": "integer", "description": "From civitai_list_models latest_version_id"},
                "dest_name":        {"type": "string", "description": "Optional filename override"},
            },
            "required": ["model_version_id"],
        },
    },
    {
        "name": "civitai_analyze_workflow",
        "description": "List what models/nodes a ComfyUI workflow requires.",
        "inputSchema": {
            "type": "object",
            "properties": {"workflow": {"type": "object", "description": "ComfyUI workflow dict"}},
            "required": ["workflow"],
        },
    },
    {
        "name": "civitai_deploy_workflow",
        "description": "Submit a ComfyUI API-format workflow to the running ComfyUI instance (port 8188).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow":  {"type": "object", "description": "ComfyUI API-format prompt dict"},
                "client_id": {"type": "string", "description": "Submission identifier", "default": "goldberg"},
            },
            "required": ["workflow"],
        },
    },
    {
        "name": "comfyui_queue",
        "description": "Check how many ComfyUI jobs are running/pending.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "comfyui_poll",
        "description": "Wait for a ComfyUI job to finish and return output image paths.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt_id": {"type": "string", "description": "From civitai_deploy_workflow"},
                "timeout":   {"type": "integer", "description": "Max seconds to wait", "default": 180},
            },
            "required": ["prompt_id"],
        },
    },
    {
        "name": "comfyui_view",
        "description": "Open output image(s) in the default viewer. No args opens the most recent output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt_id": {"type": "string", "description": "Open all images from this prompt"},
                "path":      {"type": "string", "description": "Open a specific file path directly"},
            },
        },
    },
    {
        "name": "comfyui_list_outputs",
        "description": "List recent ComfyUI output images with paths and view URLs.",
        "inputSchema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "How many recent files to return", "default": 10}},
        },
    },
    {
        "name": "runpod_list_pods",
        "description": "List all RunPod GPU pods in the account.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "runpod_get_pod",
        "description": "Get status and details for one RunPod pod.",
        "inputSchema": {
            "type": "object",
            "properties": {"pod_id": {"type": "string", "description": "Pod ID"}},
            "required": ["pod_id"],
        },
    },
    {
        "name": "runpod_create_pod",
        "description": "Spin up a new on-demand RunPod GPU pod. INCURS COST — GPU billing starts immediately.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gpu_type": {"type": "string", "description": "GPU name string, e.g. 'NVIDIA GeForce RTX 4090'"},
                "image":    {"type": "string", "description": "Docker image to run"},
                "name":     {"type": "string", "description": "Pod display name", "default": "goldberg-pod"},
                "env":      {"type": "object", "description": "Env vars to pass into the pod"},
            },
        },
    },
    {
        "name": "runpod_stop_pod",
        "description": "Stop (pause) a RunPod pod — keeps disk, stops GPU billing.",
        "inputSchema": {
            "type": "object",
            "properties": {"pod_id": {"type": "string", "description": "Pod ID"}},
            "required": ["pod_id"],
        },
    },
    {
        "name": "runpod_terminate_pod",
        "description": "Permanently delete a RunPod pod. All data lost — irreversible.",
        "inputSchema": {
            "type": "object",
            "properties": {"pod_id": {"type": "string", "description": "Pod ID"}},
            "required": ["pod_id"],
        },
    },
    {
        "name": "b2_list_files",
        "description": "List files in the Backblaze B2 bucket.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Optional filename prefix filter"},
                "limit":  {"type": "integer", "description": "Max files to return", "default": 100},
            },
        },
    },
    {
        "name": "b2_upload_file",
        "description": "Upload a local file to the B2 bucket.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "description": "Absolute path to the file to upload"},
                "dest":       {"type": "string", "description": "Remote filename (defaults to basename)"},
            },
            "required": ["local_path"],
        },
    },
    {
        "name": "b2_download_file",
        "description": "Download a file from the B2 bucket to a local path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "remote_name": {"type": "string", "description": "Filename in the bucket (from b2_list_files)"},
                "dest":        {"type": "string", "description": "Local save path (defaults to ~/Downloads/{filename})"},
            },
            "required": ["remote_name"],
        },
    },
]

# Native tool-calling defs — same param shapes as CUSTOM_SCHEMAS, OpenAI/Ollama
# function-call format (registry.py extends OLLAMA_TOOL_DEFS with these).
CUSTOM_OLLAMA_DEFS: list = [
    {"type": "function", "function": {"name": s["name"], "description": s["description"], "parameters": s["inputSchema"]}}
    for s in CUSTOM_SCHEMAS
]

CUSTOM_DOCS: str = """
### Goldberg Art Pipeline Tools

**civitai_list_models** — Search CivitAI for checkpoints, LoRAs, etc.
```json
{"tool": "civitai_list_models", "params": {"query": "realistic portrait", "type": "Checkpoint", "limit": 10}}
```
- `type`: Checkpoint | LORA | TextualInversion | Controlnet | VAE | Upscaler

**civitai_fetch_workflow** — Pull workflow JSON from a CivitAI image or model URL
```json
{"tool": "civitai_fetch_workflow", "params": {"url": "https://civitai.com/images/12345"}}
```

**civitai_download_model** — Download a model version into local_models/
```json
{"tool": "civitai_download_model", "params": {"model_version_id": 123456, "dest_name": "my_model.safetensors"}}
```
- `model_version_id`: from civitai_list_models latest_version_id
- `dest_name`: optional filename override

**civitai_analyze_workflow** — List what models/nodes a workflow requires
```json
{"tool": "civitai_analyze_workflow", "params": {"workflow": {...}}}
```

**civitai_deploy_workflow** — Submit workflow to ComfyUI
```json
{"tool": "civitai_deploy_workflow", "params": {"workflow": {...}}}
```
- ComfyUI must be running on port 8188

**comfyui_queue** — Check how many jobs are running/pending
```json
{"tool": "comfyui_queue", "params": {}}
```

**comfyui_poll** — Wait for a job to finish and return output image paths
```json
{"tool": "comfyui_poll", "params": {"prompt_id": "abc-123", "timeout": 180}}
```

**comfyui_view** — Open output image(s) in the default viewer
```json
{"tool": "comfyui_view", "params": {"prompt_id": "abc-123"}}
{"tool": "comfyui_view", "params": {"path": "/abs/path/to/image.png"}}
{"tool": "comfyui_view", "params": {}}
```
- No args opens the most recent output image

**comfyui_list_outputs** — List recent output images with paths and view URLs
```json
{"tool": "comfyui_list_outputs", "params": {"n": 10}}
```

**runpod_list_pods** — List all RunPod GPU pods in the account
```json
{"tool": "runpod_list_pods", "params": {}}
```

**runpod_get_pod** — Get status and details for one pod
```json
{"tool": "runpod_get_pod", "params": {"pod_id": "abc123"}}
```

**runpod_create_pod** — Spin up a new on-demand GPU pod. INCURS COST.
```json
{"tool": "runpod_create_pod", "params": {"gpu_type": "NVIDIA GeForce RTX 4090", "image": "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04", "name": "goldberg-pod", "env": {"MY_VAR": "value"}}}
```
- `gpu_type`: GPU name string (check runpod_list_pods for what's in the account)
- `image`: Docker image to run
- `env`: optional dict of env vars to pass into the pod

**runpod_stop_pod** — Stop (pause) a pod — keeps disk, stops GPU billing
```json
{"tool": "runpod_stop_pod", "params": {"pod_id": "abc123"}}
```

**runpod_terminate_pod** — Permanently delete a pod (all data lost)
```json
{"tool": "runpod_terminate_pod", "params": {"pod_id": "abc123"}}
```

**b2_list_files** — List files in the Backblaze B2 bucket
```json
{"tool": "b2_list_files", "params": {"prefix": "outputs/", "limit": 50}}
```
- `prefix`: optional filename prefix filter
- `limit`: max files to return (default 100)

**b2_upload_file** — Upload a local file to B2
```json
{"tool": "b2_upload_file", "params": {"local_path": "/abs/path/to/file.png", "dest": "outputs/myimage.png"}}
```
- `dest`: remote filename in bucket (defaults to file basename)

**b2_download_file** — Download a file from B2
```json
{"tool": "b2_download_file", "params": {"remote_name": "outputs/myimage.png", "dest": "/abs/local/path.png"}}
```
- `dest`: local save path (defaults to ~/Downloads/{filename})
"""
