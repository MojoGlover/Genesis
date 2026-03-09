"""
Ollama Provider
Local LLM provider using Ollama
"""
from __future__ import annotations
import httpx
import time
from typing import Dict, Any, Optional
from .base import BaseProvider


class OllamaProvider(BaseProvider):
    """Ollama local model provider"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model = config.get("name", "llama3.1:70b")
        self.base_url = config.get("base_url", "http://localhost:11434")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate completion using Ollama"""
        start = time.time()

        # Build messages array
        messages = []
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        messages.append({
            "role": "user",
            "content": prompt
        })

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature or self.config.get("temperature", 0.7),
                        "num_predict": max_tokens or self.config.get("max_tokens", 1000)
                    }
                }
            )
            response.raise_for_status()
            data = response.json()

        latency = int((time.time() - start) * 1000)

        return {
            "content": data["message"]["content"],
            "model": self.model,
            "latency_ms": latency
        }

    def get_name(self) -> str:
        return f"ollama:{self.model}"

    def is_available(self) -> bool:
        """Check if Ollama is reachable (sync check)"""
        try:
            import httpx as _httpx
            resp = _httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False
