"""
Ollama Provider
For local models: Llama 3.1 70B, Phi-4, CodeLlama
"""
import time
import httpx
from typing import Dict, Any, Optional
from .base import BaseProvider


class OllamaProvider(BaseProvider):
    """Provider for local Ollama models"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.model = config.get("name", "llama3.1:70b")
        self.timeout = config.get("timeout", 120)
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate response using Ollama"""
        start = time.time()
        
        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Prepare request
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {}
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if temperature is not None:
            payload["options"]["temperature"] = temperature
        
        # Make request
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            print(f"DEBUG: Calling {self.base_url}/api/chat with model {self.model}")
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload
            )
            response.raise_for_status()
            data = response.json()
        
        latency_ms = int((time.time() - start) * 1000)
        
        return {
            "content": data["message"]["content"],
            "model": self.model,
            "tokens_used": data.get("eval_count", 0),
            "latency_ms": latency_ms
        }
    
    def get_name(self) -> str:
        return f"ollama:{self.model}"
    
    def is_available(self) -> bool:
        """Check if Ollama is running"""
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
