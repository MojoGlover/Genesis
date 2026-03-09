"""ollamactl/client.py — Ollama API client."""
from __future__ import annotations
import json
import sys
import urllib.request
import urllib.error
from typing import Optional

from .config import OLLAMA_BASE, TIMEOUT


class OllamaClient:
    def __init__(self, base: str = OLLAMA_BASE):
        self.base = base.rstrip("/")

    def _get(self, path: str) -> dict:
        url = f"{self.base}{path}"
        req = urllib.request.urlopen(url, timeout=TIMEOUT)
        return json.loads(req.read().decode())

    def _post(self, path: str, payload: dict) -> dict:
        url  = f"{self.base}{path}"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read().decode())

    def tags(self) -> list[dict]:
        return self._get("/api/tags").get("models", [])

    def pull(self, model: str) -> None:
        """Pull a model. Streams progress to stdout."""
        url  = f"{self.base}/api/pull"
        data = json.dumps({"name": model}).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line.decode())
                    status = obj.get("status", "")
                    total    = obj.get("total", 0)
                    completed = obj.get("completed", 0)
                    if total:
                        pct = int(completed / total * 100)
                        print(f"\r  Pulling {model}: {status} {pct}%   ", end="", flush=True)
                    else:
                        print(f"\r  {status}                              ", end="", flush=True)
                except Exception:
                    pass
        print()

    def delete(self, model: str) -> None:
        url  = f"{self.base}/api/delete"
        data = json.dumps({"name": model}).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT)

    def chat(self, model: str, prompt: str) -> str:
        """Quick test chat."""
        resp = self._post("/api/chat", {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        })
        return resp.get("message", {}).get("content", "")


def check_status(base: str = OLLAMA_BASE) -> tuple[bool, str]:
    """Returns (reachable, status_message)."""
    try:
        client = OllamaClient(base)
        models = client.tags()
        names  = [m.get("name", "") for m in models]
        return True, f"Online — {len(names)} model(s): {', '.join(names) or 'none'}"
    except Exception as e:
        return False, f"Offline — {type(e).__name__}: {e}"


def list_models(base: str = OLLAMA_BASE) -> list[dict]:
    try:
        return OllamaClient(base).tags()
    except Exception as e:
        print(f"  ✗ Could not reach Ollama: {e}")
        return []


def pull_model(model: str, base: str = OLLAMA_BASE) -> None:
    try:
        OllamaClient(base).pull(model)
    except Exception as e:
        print(f"  ✗ Pull failed: {e}")
        sys.exit(1)
