# model_router.py
# THE MODEL ROUTER
#
# Responsibility:
#   Routes generation requests to the correct model provider based on
#   configuration, task type, or cost/performance tradeoffs.
#
# What does NOT belong here:
#   - Provider-specific implementation details (each provider gets its own adapter)
#   - Training data or prompt experiments
#   - Embedding logic (that belongs in rag/embedding_router.py)

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationConfig:
    """
    Parameters for a single generation request.
    Pass to ModelRouter.complete() to control model behaviour.
    """
    model: str | None = None           # override the router's default model
    temperature: float = 0.7
    max_tokens: int = 1024
    stop_sequences: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # provider-specific params


class ModelRouter(ABC):
    """
    Abstract base class for model generation routing.

    A ModelRouter selects the appropriate provider and model for each
    request, then delegates to a ProviderAdapter. Agents subclass this
    to implement routing strategies (e.g. fast model for simple tasks,
    large model for complex reasoning).

    Example agent implementation:
        class OllamaRouter(ModelRouter):
            def __init__(self, adapter):
                self._adapter = adapter

            def complete(self, prompt, config=None):
                cfg = config or GenerationConfig()
                return self._adapter.generate(prompt, temperature=cfg.temperature)

            def list_providers(self):
                return [self._adapter.name]
    """

    @abstractmethod
    def complete(self, prompt: str, config: GenerationConfig | None = None) -> str:
        """
        Generate a completion for the given prompt.

        Args:
            prompt: The full prompt string (including any system context).
            config: Optional generation parameters. Router uses defaults if None.

        Returns:
            The generated text as a string.

        Raises:
            RuntimeError: If no provider is available or generation fails.
        """

    @abstractmethod
    def list_providers(self) -> list[str]:
        """
        Return the names of all configured/available providers.
        Used by healthcheck.py to verify connectivity.
        """

    def complete_with_system(
        self, system: str, user: str, config: GenerationConfig | None = None
    ) -> str:
        """
        Convenience method: combine a system prompt and user message, then complete.
        Agents may override for provider-native system prompt support.
        """
        cfg = config or GenerationConfig()
        cfg.system_prompt = system
        return self.complete(user, cfg)
