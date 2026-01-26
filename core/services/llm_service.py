"""
LLM Service - Unified interface to AI providers via ProviderRouter
Replaces hardcoded OpenAI client in gradio_interface.py
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class LLMService:
    """Wraps ProviderRouter for sync + async LLM generation"""

    def __init__(self):
        self._router = None
        self._available = False
        self._init_router()

    def _init_router(self):
        """Initialize the provider router"""
        try:
            from core.providers.router import get_router
            self._router = get_router()
            self._available = True
            logger.info("LLMService initialized with ProviderRouter")
        except Exception as e:
            logger.warning(f"ProviderRouter unavailable, falling back to direct OpenAI: {e}")
            self._init_openai_fallback()

    def _init_openai_fallback(self):
        """Fallback to direct OpenAI if router unavailable"""
        try:
            import os
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self._available = True
            logger.info("LLMService initialized with OpenAI fallback")
        except Exception as e:
            logger.error(f"No LLM provider available: {e}")
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def generate_async(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        complexity: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """Async generation via ProviderRouter"""
        if not self._available:
            return {"success": False, "content": "", "error": "No LLM provider available"}

        start = time.time()
        try:
            if self._router:
                result = await self._router.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    complexity=complexity,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                latency_ms = int((time.time() - start) * 1000)
                return {
                    "success": True,
                    "content": result.get("content", ""),
                    "model": result.get("model", "unknown"),
                    "provider": result.get("provider", "unknown"),
                    "latency_ms": latency_ms,
                }
            else:
                # OpenAI fallback (sync call in async context)
                return self._openai_generate(
                    prompt, system_prompt, temperature, max_tokens
                )
        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            return {"success": False, "content": "", "error": str(e)}

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        complexity: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """Sync wrapper around async generation"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context - use fallback
                return self._openai_generate(
                    prompt, system_prompt, temperature, max_tokens
                )
            return loop.run_until_complete(
                self.generate_async(prompt, system_prompt, complexity, temperature, max_tokens)
            )
        except RuntimeError:
            # No event loop - create one
            return asyncio.run(
                self.generate_async(prompt, system_prompt, complexity, temperature, max_tokens)
            )

    def generate_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """Generate from a list of chat messages.

        Flattens message list into a single prompt for the router,
        or uses OpenAI chat completions directly when available.
        """
        if not self._available:
            return {"success": False, "content": "", "error": "No LLM provider available"}

        start = time.time()

        # Prefer direct OpenAI chat completions for message-based calls
        if hasattr(self, "_openai_client"):
            return self._openai_chat(messages, system_prompt, temperature, max_tokens)

        # Flatten messages into a prompt for the router
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt_parts.append(f"{role}: {content}")
        flat_prompt = "\n".join(prompt_parts)

        return self.generate(
            prompt=flat_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _openai_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """Direct OpenAI generation fallback"""
        if not hasattr(self, "_openai_client"):
            return {"success": False, "content": "", "error": "OpenAI client not available"}

        start = time.time()
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self._openai_client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency_ms = int((time.time() - start) * 1000)
            return {
                "success": True,
                "content": response.choices[0].message.content,
                "model": "gpt-4",
                "provider": "openai",
                "latency_ms": latency_ms,
            }
        except Exception as e:
            logger.error(f"OpenAI generation error: {e}")
            return {"success": False, "content": "", "error": str(e)}

    def _openai_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """Direct OpenAI chat completions"""
        start = time.time()
        try:
            chat_messages = []
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            chat_messages.extend(messages)

            response = self._openai_client.chat.completions.create(
                model="gpt-4",
                messages=chat_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency_ms = int((time.time() - start) * 1000)
            return {
                "success": True,
                "content": response.choices[0].message.content,
                "model": "gpt-4",
                "provider": "openai",
                "latency_ms": latency_ms,
            }
        except Exception as e:
            logger.error(f"OpenAI chat error: {e}")
            return {"success": False, "content": "", "error": str(e)}


# Singleton
_llm_service = None


def get_llm_service() -> LLMService:
    """Get or create LLMService singleton"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
