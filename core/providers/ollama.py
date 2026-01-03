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
    
    def __init__(self, model: str = "llama3.1:70b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
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
        
        print(f"DEBUG: Calling {self.base_url}/api/chat with model {self.model}")
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens
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
    
    async def health_check(self) -> bool:
        """Check if Ollama is running"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except:
            return False
