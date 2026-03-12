# provider_adapter.py
# THE PROVIDER ADAPTER BASE
#
# Responsibility:
#   Defines the contract that every model provider adapter must implement.
#   Concrete adapters (e.g. ollama_adapter.py, openai_adapter.py) inherit from this.
#
# What does NOT belong here:
#   - Provider-specific API calls (each provider gets its own file)
#   - Routing logic (that belongs in model_router.py)
#   - Embedding adapters (that belongs in rag/)

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(Exception):
    """Raised when a provider call fails. Include provider name and reason."""


class ProviderAdapter(ABC):
    """
    Abstract base class for model provider integrations.

    Each supported provider (Ollama, OpenAI, Anthropic, Mistral, etc.)
    gets its own concrete subclass in the agent's models/ directory.
    The ModelRouter holds a reference to one or more ProviderAdapters
    and delegates generation calls to them.

    Example concrete adapter:
        class OllamaAdapter(ProviderAdapter):
            name = "ollama"

            def generate(self, prompt, **kwargs):
                # call Ollama REST API
                ...

            def is_available(self):
                # ping /api/tags endpoint
                ...
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this provider (e.g. "ollama", "openai", "anthropic").
        Must match the provider name used in GenerationConfig and routing logic.
        """

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """
        Send a prompt to the provider and return the generated text.

        Args:
            prompt:   The full prompt string.
            **kwargs: Provider-specific parameters (model, temperature, max_tokens, etc.).

        Returns:
            The generated completion as a string.

        Raises:
            ProviderError: If the API call fails or returns an error.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check whether this provider is reachable and operational.
        Used by healthcheck.py and the ModelRouter's fallback logic.

        Returns True if the provider can accept requests, False otherwise.
        Should never raise — catch all exceptions internally and return False.
        """

    def default_model(self) -> str | None:
        """
        Return the default model name for this provider, or None if
        the provider does not have a meaningful default. Override in subclass.
        """
        return None
