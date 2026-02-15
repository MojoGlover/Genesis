"""LangChain integration adapter for ai_starter."""

from typing import Any, AsyncIterator

from pydantic import BaseModel

from ai_starter.llm.client import OllamaClient
from ai_starter.llm.schemas import Message
from ai_starter.tools.registry import ToolRegistry


class LangChainConfig(BaseModel):
    """Configuration for LangChain integration."""
    enable_streaming: bool = False
    max_iterations: int = 10
    early_stopping_method: str = "generate"


class LangChainAdapter:
    """Adapter to use ai_starter components with LangChain patterns."""

    def __init__(
        self,
        llm_client: OllamaClient,
        tool_registry: ToolRegistry,
        config: LangChainConfig,
    ):
        self.llm = llm_client
        self.tools = tool_registry
        self.config = config

    async def invoke(self, messages: list[Message], **kwargs: Any) -> str:
        """Invoke LLM (LangChain-style interface)."""
        response = await self.llm.generate(messages, **kwargs)
        return response.content

    async def stream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[str]:
        """Stream LLM response (placeholder for streaming support)."""
        # Placeholder - would implement actual streaming
        response = await self.invoke(messages, **kwargs)
        for chunk in response.split():
            yield chunk + " "

    def as_langchain_llm(self) -> dict[str, Any]:
        """Convert to LangChain-compatible LLM interface."""
        return {
            "llm_type": "ollama",
            "model": self.llm.settings.model,
            "temperature": self.llm.settings.temperature,
            "invoke": self.invoke,
            "stream": self.stream,
        }

    def as_langchain_tools(self) -> list[dict[str, Any]]:
        """Convert tools to LangChain-compatible format."""
        lc_tools = []
        for tool in self.tools.list_tools():
            lc_tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "func": tool.fn,
            })
        return lc_tools


def create_langchain_adapter(
    llm: OllamaClient,
    tools: ToolRegistry,
    config: dict[str, Any],
) -> LangChainAdapter:
    """Factory to create LangChain adapter."""
    lc_config = LangChainConfig(**config.get("langchain", {}))
    return LangChainAdapter(llm, tools, lc_config)
