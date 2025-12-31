"""
OpenAI Provider
For GPT models (cloud fallback)
"""
import os
import time
from typing import Dict, Any, Optional
from .base import BaseProvider

class OpenAIProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model = config.get("name", "gpt-4o")
        self.api_key = os.getenv(config.get("api_key_env", "OPENAI_API_KEY"))
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.api_key)
        start = time.time()
        
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt or "You are helpful."},
                {"role": "user", "content": prompt}
            ]
        )
        
        return {
            "content": response.choices[0].message.content,
            "model": self.model,
            "tokens_used": response.usage.total_tokens,
            "latency_ms": int((time.time() - start) * 1000)
        }
    
    def get_name(self) -> str:
        return f"openai:{self.model}"
    
    def is_available(self) -> bool:
        return self.api_key is not None