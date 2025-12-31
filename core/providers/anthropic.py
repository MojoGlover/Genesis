"""
Anthropic Provider
For Claude API (cloud fallback)
"""
import os
import time
from typing import Dict, Any, Optional
from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    """Provider for Anthropic Claude API"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model = config.get("name", "claude-sonnet-4-20250514")
        self.api_key = os.getenv(config.get("api_key_env", "ANTHROPIC_API_KEY"))
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate response using Claude API"""
        if not self.api_key:
            raise ValueError("Anthropic API key not found")
        
        start = time.time()
        
        try:
            from anthropic import AsyncAnthropic
            
            client = AsyncAnthropic(api_key=self.api_key)
            
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens or 4096,
                temperature=temperature or 0.7,
                system=system_prompt or "You are a helpful assistant.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            latency_ms = int((time.time() - start) * 1000)
            
            return {
                "content": response.content[0].text,
                "model": self.model,
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
                "latency_ms": latency_ms
            }
        except Exception as e:
            raise Exception(f"Anthropic API error: {str(e)}")
    
    def get_name(self) -> str:
        return f"anthropic:{self.model}"
    
    def is_available(self) -> bool:
        """Check if API key is configured"""
        return self.api_key is not None
