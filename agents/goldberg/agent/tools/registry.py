"""
registry.py — Tool registry for Engineer0's ReAct loop.

Maps tool names to functions. Generates tool documentation injected
into the system prompt so the LLM knows what it can do and how to call it.

Tool call format (LLM outputs this JSON in its response):
    ```json
    {"tool": "shell", "params": {"command": "ls -la", "cwd": "/tmp"}}
    ```
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Tool documentation ────────────────────────────────────────────────────────

TOOL_DOCS = """
## TOOLS

You have tools. Use them to get things done. When you need to use a tool,
output a JSON block like this (and ONLY this — no other text in that turn):

```json
{"tool": "<tool_name>", "params": {<parameters>}}
```

After the tool runs, you will see the result and can continue reasoning or
call another tool. When done, output your final response as plain text.

### Available Tools

**shell** — Run any shell command
```json
{"tool": "shell", "params": {"command": "ls -la /tmp", "cwd": "/Users/darnieglover/ai/cmptrblk", "timeout": 30}}
```
- `command`: shell command string (required)
- `cwd`: working directory (default: cmptrblk root)
- `timeout`: seconds (default: 60)
- `confirm_destructive`: true to allow rm -rf, force push, etc. (default: false)

**read_file** — Read a file with line numbers
```json
{"tool": "read_file", "params": {"path": "/path/to/file.py", "offset": 0, "limit": 100}}
```
- `path`: file path (required)
- `offset`: start line (default: 0)
- `limit`: max lines to return (default: 200)

**write_file** — Write content to a file (creates dirs if needed)
```json
{"tool": "write_file", "params": {"path": "/path/to/file.py", "content": "...", "overwrite": true}}
```

**patch_file** — Replace an exact string in a file
```json
{"tool": "patch_file", "params": {"path": "/path/to/file.py", "old_string": "old code", "new_string": "new code"}}
```
- Fails if old_string appears more than once. Add more context to make it unique.

**list_dir** — List files in a directory
```json
{"tool": "list_dir", "params": {"path": "/path/to/dir", "pattern": "*.py", "recursive": false}}
```

**search_files** — Search for a pattern across files
```json
{"tool": "search_files", "params": {"path": "/path/to/search", "pattern": "def build_graph", "file_glob": "*.py"}}
```

**python** — Execute Python code in a sandbox
```json
{"tool": "python", "params": {"code": "print(1 + 1)", "cwd": "/tmp"}}
```

**web_fetch** — Fetch a URL and return its content
```json
{"tool": "web_fetch", "params": {"url": "https://example.com/api"}}
```

**web_search** — Search DuckDuckGo for quick answers
```json
{"tool": "web_search", "params": {"query": "python asyncio timeout example"}}
```

**api_call** — Make an HTTP API call
```json
{"tool": "api_call", "params": {"url": "http://localhost:5001/health", "method": "GET"}}
```

**git_status** — Git status for a repo
```json
{"tool": "git_status", "params": {"repo_path": "/Users/darnieglover/ai/cmptrblk/Engineer0"}}
```

**git_add** — Stage files
```json
{"tool": "git_add", "params": {"paths": ["file.py", "other.py"], "repo_path": "."}}
```

**git_commit** — Commit staged changes
```json
{"tool": "git_commit", "params": {"message": "feat: add thing", "repo_path": "."}}
```

**git_push** — Push to remote
```json
{"tool": "git_push", "params": {"repo_path": ".", "branch": "main"}}
```

**git_log** — Recent commits
```json
{"tool": "git_log", "params": {"repo_path": ".", "n": 10}}
```

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

**comfyui_view** — Open output image(s) in Preview
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

**runpod_create_pod** — Spin up a new on-demand GPU pod
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

### Rules
- Use the minimum number of tool calls needed.
- Prefer read_file before editing — always know what you're changing.
- Use patch_file for small targeted edits; write_file for full rewrites.
- Always git_fetch before git_push.
- If a tool fails, diagnose before retrying.
- If you hit max iterations without finishing, summarize what you did and what remains.
"""


# ── Registry ──────────────────────────────────────────────────────────────────

def build_executor() -> Callable[[str, dict], str]:
    """
    Build and return the tool executor function.
    Called once at agent boot. Returns a closure over all tool modules.
    """
    from agent.tools import shell, files, git_tool, python_repl, web, civitai_tool, comfyui_tool, runpod_tool, b2_tool

    def execute(tool_name: str, params: dict) -> str:
        """Dispatch a tool call. Returns result as string for LLM context."""
        try:
            if tool_name == "shell":
                result = shell.run(**params)
                return shell.format_result(result)

            elif tool_name == "read_file":
                result = files.read(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"File: {result['path']} (lines {result['shown']} of {result['total_lines']})\n{result['content']}"

            elif tool_name == "write_file":
                result = files.write(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"Written: {result['path']} ({result['bytes']} bytes)"

            elif tool_name == "patch_file":
                result = files.patch(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"Patched: {result['path']}"

            elif tool_name == "list_dir":
                result = files.list_dir(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"{result['path']} ({result['count']} files):\n" + "\n".join(result["files"])

            elif tool_name == "search_files":
                result = files.search(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                if not result["matches"]:
                    return f"No matches for '{result['pattern']}'"
                return f"{result['count']} match(es):\n" + "\n".join(result["matches"])

            elif tool_name == "python":
                result = python_repl.run(**params)
                return python_repl.format_result(result)

            elif tool_name == "web_fetch":
                result = web.fetch(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return result["content"][:10_000]

            elif tool_name == "web_search":
                result = web.search(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                if not result["results"]:
                    return f"No results for: {result['query']}"
                lines = [f"Results for: {result['query']}"]
                for r in result["results"]:
                    lines.append(f"\n{r['title']}\n{r['url']}\n{r['snippet']}")
                return "\n".join(lines)

            elif tool_name == "api_call":
                result = web.api_call(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"HTTP {result['status']}\n{result['content'][:5_000]}"

            elif tool_name == "git_status":
                return git_tool.status(**params)
            elif tool_name == "git_add":
                return git_tool.add(**params)
            elif tool_name == "git_commit":
                return git_tool.commit(**params)
            elif tool_name == "git_push":
                return git_tool.push(**params)
            elif tool_name == "git_log":
                return git_tool.log(**params)
            elif tool_name == "git_diff":
                return git_tool.diff(**params)
            elif tool_name == "git_fetch":
                return git_tool.fetch(**params)
            elif tool_name == "git_pull":
                return git_tool.pull(**params)
            elif tool_name == "git_clone":
                return git_tool.clone(**params)

            elif tool_name == "civitai_list_models":
                result = civitai_tool.list_models(**params)
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

            elif tool_name == "civitai_fetch_workflow":
                result = civitai_tool.fetch_workflow(**params)
                if not result["ok"]:
                    return f"civitai_fetch_workflow failed: {result.get('error')}"
                note = f"\nNote: {result['note']}" if result.get("note") else ""
                return f"Source: {result['source']}{note}\n{json.dumps(result['workflow'], indent=2)[:8000]}"

            elif tool_name == "civitai_download_model":
                result = civitai_tool.download_model(**params)
                if not result["ok"]:
                    return f"civitai_download_model failed: {result.get('error')}"
                note = f" ({result['note']})" if result.get("note") else ""
                return f"Downloaded: {result['path']} ({result['size_mb']} MB){note}"

            elif tool_name == "civitai_analyze_workflow":
                result = civitai_tool.analyze_workflow(**params)
                if not result["ok"]:
                    return f"civitai_analyze_workflow failed: {result.get('error')}"
                lines = [result["summary"]]
                if result["required_models"]:
                    lines.append("\nRequired models:")
                    for m in result["required_models"]:
                        lines.append(f"  [{m['type']}] {m['name']}")
                return "\n".join(lines)

            elif tool_name == "civitai_deploy_workflow":
                result = civitai_tool.deploy_workflow(**params)
                if not result["ok"]:
                    return f"civitai_deploy_workflow failed: {result.get('error')}"
                return f"Queued — prompt_id: {result['prompt_id']}  position: {result['queue_position']}"

            elif tool_name == "comfyui_queue":
                result = comfyui_tool.queue_status()
                if not result["ok"]:
                    return f"comfyui_queue failed: {result.get('error')}"
                return f"ComfyUI queue — running: {result['running']}  pending: {result['pending']}"

            elif tool_name == "comfyui_poll":
                result = comfyui_tool.poll_result(**params)
                if not result["ok"]:
                    return f"comfyui_poll failed: {result.get('error')}"
                if not result["images"]:
                    return "Job finished but no images in output."
                lines = [f"Done — {len(result['images'])} image(s):"]
                for img in result["images"]:
                    lines.append(f"  {img['path']}")
                    lines.append(f"  View: {img['view_url']}")
                return "\n".join(lines)

            elif tool_name == "comfyui_view":
                result = comfyui_tool.view_output(**params)
                if not result["ok"]:
                    return f"comfyui_view failed: {result.get('error')}"
                note = f"\nNote: {result['note']}" if result.get("note") else ""
                return f"Opened {len(result['opened'])} image(s):\n" + "\n".join(result["opened"]) + note

            elif tool_name == "comfyui_list_outputs":
                result = comfyui_tool.list_outputs(**params)
                if not result["ok"]:
                    return f"comfyui_list_outputs failed: {result.get('error')}"
                if not result["images"]:
                    return result.get("note", "No output images found.")
                lines = [f"{len(result['images'])} recent output(s):"]
                for img in result["images"]:
                    lines.append(f"  {img['filename']}  {img['size_kb']}KB  {img['modified']}")
                    lines.append(f"    {img['path']}")
                return "\n".join(lines)

            elif tool_name == "runpod_list_pods":
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

            elif tool_name == "runpod_get_pod":
                result = runpod_tool.get_pod(**params)
                if not result["ok"]:
                    return f"runpod_get_pod failed: {result.get('error')}"
                import json as _json
                return _json.dumps(result["pod"], indent=2)

            elif tool_name == "runpod_create_pod":
                result = runpod_tool.create_pod(**params)
                if not result["ok"]:
                    return f"runpod_create_pod failed: {result.get('error')}"
                p = result["pod"]
                gpu = p.get("machine", {}).get("gpuDisplayName", "unknown GPU")
                return f"Pod created — id: {p['id']}  name: {p['name']}  gpu: {gpu}  status: {p['desiredStatus']}  ${p.get('costPerHr', 0):.3f}/hr"

            elif tool_name == "runpod_stop_pod":
                result = runpod_tool.stop_pod(**params)
                if not result["ok"]:
                    return f"runpod_stop_pod failed: {result.get('error')}"
                p = result.get("pod", {})
                return f"Pod stopped — id: {p.get('id', params.get('pod_id'))}  status: {p.get('desiredStatus', 'EXITED')}"

            elif tool_name == "runpod_terminate_pod":
                result = runpod_tool.terminate_pod(**params)
                if not result["ok"]:
                    return f"runpod_terminate_pod failed: {result.get('error')}"
                return f"Pod terminated: {result['terminated']}"

            elif tool_name == "b2_list_files":
                result = b2_tool.list_files(**params)
                if not result["ok"]:
                    return f"b2_list_files failed: {result.get('error')}"
                if not result["files"]:
                    return f"No files in bucket '{result.get('bucket', '')}'."
                lines = [f"{result['count']} file(s) in {result['bucket']}:"]
                for f in result["files"]:
                    lines.append(f"  {f['name']}  {f['size_kb']}KB")
                return "\n".join(lines)

            elif tool_name == "b2_upload_file":
                result = b2_tool.upload_file(**params)
                if not result["ok"]:
                    return f"b2_upload_file failed: {result.get('error')}"
                return f"Uploaded: {result['name']} ({result['size_kb']}KB) → {result['bucket']}"

            elif tool_name == "b2_download_file":
                result = b2_tool.download_file(**params)
                if not result["ok"]:
                    return f"b2_download_file failed: {result.get('error')}"
                return f"Downloaded: {result['name']} ({result['size_kb']}KB) → {result['path']}"

            else:
                return f"Unknown tool: '{tool_name}'. Check TOOLS section for available tools."

        except TypeError as e:
            return f"Tool '{tool_name}' called with wrong params: {e}"
        except Exception as e:
            logger.error(f"[registry] Tool '{tool_name}' error: {e}")
            return f"Tool error: {e}"

    return execute


def parse_tool_call(text: str) -> dict | None:
    """
    Extract a tool call JSON from LLM output.
    Looks for ```json ... ``` block first, then bare JSON with "tool" key.
    Returns None if no valid tool call found.
    """
    # Try fenced code block first
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if block_match:
        try:
            data = json.loads(block_match.group(1))
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass

    # Try bare JSON object with "tool" key
    bare_match = re.search(r'\{[^{}]*"tool"\s*:[^{}]*\}', text, re.DOTALL)
    if bare_match:
        try:
            data = json.loads(bare_match.group(0))
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass

    return None
