"""
Provider Router
Intelligently routes requests to the best available provider
"""
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from .base import BaseProvider
from .ollama import OllamaProvider
from .anthropic import AnthropicProvider
from .openai import OpenAIProvider
from .google import GoogleProvider

class ProviderRouter:
    """Routes requests to appropriate AI provider"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.providers = self._initialize_providers()
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    
    def _initialize_providers(self) -> Dict[str, BaseProvider]:
        """Initialize all configured providers"""
        providers = {}
        
        # Local providers
        if "local" in self.config["models"]:
            local_config = self.config["models"]["local"]
            
            # Primary local model
            if "primary" in local_config:
                providers["local_primary"] = OllamaProvider(local_config["primary"])
            
            # Fast local model
            if "fast" in local_config:
                providers["local_fast"] = OllamaProvider(local_config["fast"])
            
            # Specialist models
            if "specialist" in local_config:
                for name, spec_config in local_config["specialist"].items():
                    providers[f"local_{name}"] = OllamaProvider(spec_config)
                    
        
        # Cloud providers
        if "cloud" in self.config["models"] and self.config["models"]["cloud"].get("enabled"):
            cloud_config = self.config["models"]["cloud"]
            
            if "claude" in cloud_config:
                providers["cloud_claude"] = AnthropicProvider(cloud_config["claude"])

            if "openai" in cloud_config:
                providers["cloud_openai"] = OpenAIProvider(cloud_config["openai"])
                
            if "google" in cloud_config:
                providers["cloud_google"] = GoogleProvider(cloud_config["google"])
        
        
        return providers
    
    def assess_complexity(self, prompt: str) -> str:
        """Assess prompt complexity: simple, medium, high"""
        token_count = len(prompt.split())
        
        thresholds = self.config["routing"]["complexity"]
        
        if token_count < thresholds["simple_max_tokens"]:
            return "simple"
        elif token_count < thresholds["medium_max_tokens"]:
            return "medium"
        else:
            return "high"
    
    def select_provider(
        self,
        prompt: str,
        complexity: Optional[str] = None,
        prefer_local: bool = True
    ) -> BaseProvider:
        """Select the best provider for this request"""
        
        if complexity is None:
            complexity = self.assess_complexity(prompt)
        
        # Try local first if preferred
        if prefer_local:
            if complexity == "simple" and "local_fast" in self.providers:
                provider = self.providers["local_fast"]
                if provider.is_available():
                    return provider
            
            if complexity in ["medium", "high"] and "local_primary" in self.providers:
                provider = self.providers["local_primary"]
                if provider.is_available():
                    return provider
        
        # Fallback to cloud
        if "cloud_primary" in self.providers:
            provider = self.providers["cloud_primary"]
            if provider.is_available():
                return provider
        
        raise Exception("No available providers")
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        complexity: Optional[str] = None,
        prefer_local: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate response using best available provider"""
        
        provider = self.select_provider(prompt, complexity, prefer_local)
        
        response = await provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )
        
        # Add routing metadata
        response["provider"] = provider.get_name()
        response["complexity"] = complexity or self.assess_complexity(prompt)
        
        return response


# Singleton instance
_router = None

def get_router(config_path: str = "config.yaml") -> ProviderRouter:
    """Get or create router instance"""
    global _router
    if _router is None:
        _router = ProviderRouter(config_path)
    return _router


async def route_and_generate(
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Convenience function for routing and generation"""
    router = get_router()
    return await router.generate(prompt, system_prompt, **kwargs)
