"""
Base Provider Interface
Abstract class that all AI providers must implement
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseProvider(ABC):
    """Abstract base class for AI providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a response from the AI model
        
        Returns:
            {
                "content": str,
                "model": str,
                "tokens_used": int,
                "latency_ms": int
            }
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Return provider name (e.g., 'ollama', 'anthropic')"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available/configured"""
        pass
