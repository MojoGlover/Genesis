"""
Designer Adams — ComfyUI API Client
Talks to the local ComfyUI instance.
Queue prompts, check status, get history, pull output images.
"""
import json
import uuid
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Optional


COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
BASE_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"
CLIENT_ID = str(uuid.uuid4())


class ComfyUIClient:

    def __init__(self, host: str = COMFYUI_HOST, port: int = COMFYUI_PORT):
        self.base_url = f"http://{host}:{port}"

    def is_running(self) -> bool:
        """Check if ComfyUI is up."""
        try:
            urllib.request.urlopen(f"{self.base_url}/system_stats", timeout=2)
            return True
        except Exception:
            return False

    def queue_prompt(self, workflow: dict) -> str:
        """
        Submit a workflow to ComfyUI queue.
        Returns the prompt_id.
        """
        payload = json.dumps({
            "prompt": workflow,
            "client_id": CLIENT_ID
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/prompt",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            return result["prompt_id"]

    def get_queue_status(self) -> dict:
        """Returns current queue state: running + pending."""
        with urllib.request.urlopen(f"{self.base_url}/queue") as r:
            return json.loads(r.read())

    def get_history(self, prompt_id: str) -> Optional[dict]:
        """Get result for a completed prompt."""
        with urllib.request.urlopen(f"{self.base_url}/history/{prompt_id}") as r:
            history = json.loads(r.read())
            return history.get(prompt_id)

    def get_output_images(self, prompt_id: str) -> list[bytes]:
        """Return image bytes for all outputs from a completed prompt."""
        history = self.get_history(prompt_id)
        if not history:
            return []

        images = []
        outputs = history.get("outputs", {})
        for node_id, node_output in outputs.items():
            for img_info in node_output.get("images", []):
                filename = img_info["filename"]
                subfolder = img_info.get("subfolder", "")
                img_type = img_info.get("type", "output")

                params = urllib.parse.urlencode({
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": img_type
                })
                url = f"{self.base_url}/view?{params}"
                with urllib.request.urlopen(url) as r:
                    images.append(r.read())

        return images

    def get_available_models(self, model_type: str = "checkpoints") -> list[str]:
        """
        Get list of available models of a given type.
        model_type: checkpoints, loras, vae, controlnet, upscale_models, etc.
        """
        with urllib.request.urlopen(f"{self.base_url}/object_info") as r:
            info = json.loads(r.read())

        # Find a loader node that exposes the model list
        type_to_node = {
            "checkpoints": "CheckpointLoaderSimple",
            "loras": "LoraLoader",
            "vae": "VAELoader",
            "controlnet": "ControlNetLoader",
            "upscale_models": "UpscaleModelLoader",
            "unet": "UNETLoader",
            "clip": "CLIPLoader",
        }
        node_name = type_to_node.get(model_type)
        if not node_name or node_name not in info:
            return []

        node_info = info[node_name]
        inputs = node_info.get("input", {}).get("required", {})

        # Find the model name input
        for key in ["ckpt_name", "lora_name", "vae_name", "control_net_name",
                    "model_name", "unet_name", "clip_name"]:
            if key in inputs:
                return inputs[key][0]  # First element is the list of options

        return []

    def interrupt(self) -> bool:
        """Stop current generation."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/interrupt",
                data=b"",
                method="POST"
            )
            urllib.request.urlopen(req)
            return True
        except Exception:
            return False

    def get_system_stats(self) -> dict:
        """VRAM usage, RAM, device info."""
        with urllib.request.urlopen(f"{self.base_url}/system_stats") as r:
            return json.loads(r.read())

    def load_workflow_from_file(self, path: str | Path) -> dict:
        """Load a workflow JSON from disk."""
        with open(path) as f:
            return json.load(f)

    def queue_workflow_file(self, path: str | Path) -> str:
        """Load and immediately queue a workflow file. Returns prompt_id."""
        workflow = self.load_workflow_from_file(path)
        return self.queue_prompt(workflow)


# Singleton client
client = ComfyUIClient()


def status_report() -> str:
    """Quick status string Adams can speak."""
    if not client.is_running():
        return "ComfyUI is not running."
    stats = client.get_system_stats()
    queue = client.get_queue_status()
    running = len(queue.get("queue_running", []))
    pending = len(queue.get("queue_pending", []))
    devices = stats.get("system", {}).get("devices", [])
    vram = ""
    if devices:
        d = devices[0]
        used = d.get("vram_used", 0) / (1024**3)
        total = d.get("vram_total", 0) / (1024**3)
        vram = f" | VRAM {used:.1f}/{total:.1f}GB"
    return f"ComfyUI running{vram} | Queue: {running} running, {pending} pending"
