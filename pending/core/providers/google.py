"""
Google Provider
For Gemini models (cloud fallback)
"""
import os
import time
from typing import Dict, Any, Optional
from .base import BaseProvider


class GoogleProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model = config.get("name", "gemini-2.0-flash-exp")
        self.api_key = os.getenv(config.get("api_key_env", "GOOGLE_API_KEY"))
    
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        import google.generativeai as genai
        
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        
        start = time.time()
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response = model.generate_content(full_prompt)
        
        return {
            "content": response.text,
            "model": self.model,
            "tokens_used": response.usage_metadata.total_token_count,
            "latency_ms": int((time.time() - start) * 1000)
        }
    
    def get_name(self) -> str:
        return f"google:{self.model}"
    
    def is_available(self) -> bool:
        return self.api_key is not None