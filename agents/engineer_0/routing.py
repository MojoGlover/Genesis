"""
Engineer0 Task Routing

Multi-provider routing with cloud fallback chain.
Routes tasks to: Aider (local), Claude Code, Gemini, Codex
"""

from __future__ import annotations
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Configuration for a provider."""
    name: str
    path: str
    cost: str  # "free", "free_tier", "subscription"
    best_for: list = field(default_factory=list)


@dataclass
class InvocationResult:
    """Result of invoking a provider."""
    success: bool
    provider: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration: float = 0.0
    pid: Optional[int] = None  # For background processes


# Provider configurations
PROVIDERS = {
    "aider": ProviderConfig(
        name="aider",
        path="/Users/darnieglover/Library/Python/3.11/bin/aider",
        cost="free",
        best_for=["simple", "medium", "code_generation", "refactoring"]
    ),
    "claude": ProviderConfig(
        name="claude",
        path="/opt/homebrew/bin/claude",
        cost="subscription",
        best_for=["complex", "architecture", "research", "multi_file"]
    ),
    "gemini": ProviderConfig(
        name="gemini",
        path="/opt/homebrew/bin/gemini",
        cost="free_tier",
        best_for=["code_generation", "explanation", "documentation"]
    ),
    "codex": ProviderConfig(
        name="codex",
        path="/opt/homebrew/bin/codex",
        cost="subscription",
        best_for=["code_generation", "debugging"]
    )
}

# Local models for Aider
AIDER_MODELS = {
    "simple": "ollama/codellama:13b",
    "medium": "ollama/qwen2.5-coder:32b",
    "complex": "ollama/llama3.1:70b"
}


class CloudStatus:
    """Tracks cloud service availability."""

    def __init__(self, status_path: Path):
        self.status_path = status_path
        self._status: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load status from disk."""
        if self.status_path.exists():
            try:
                self._status = json.loads(self.status_path.read_text())
            except Exception:
                self._status = {}

    def _save(self) -> None:
        """Save status to disk."""
        try:
            self.status_path.write_text(json.dumps(self._status, indent=2))
        except Exception:
            pass

    def is_available(self, provider: str) -> bool:
        """Check if a provider is available."""
        # Aider (local) is always available
        if provider == "aider":
            return True

        status = self._status.get(provider)

        # Unknown status - assume available
        if status is None:
            return True

        # Explicitly marked unavailable
        if status is False:
            # Check if enough time has passed to retry
            failed_at = self._status.get(f"{provider}_failed_at")
            if failed_at:
                failed_time = datetime.fromisoformat(failed_at)
                # Retry after 30 minutes
                if datetime.now() - failed_time > timedelta(minutes=30):
                    self._status[provider] = None  # Reset
                    self._save()
                    return True
            return False

        return True

    def mark_unavailable(self, provider: str, reason: str) -> None:
        """Mark a provider as unavailable."""
        self._status[provider] = False
        self._status[f"{provider}_reason"] = reason
        self._status[f"{provider}_failed_at"] = datetime.now().isoformat()
        self._save()
        logger.warning(f"Marked {provider} as unavailable: {reason}")

    def mark_available(self, provider: str) -> None:
        """Mark a provider as available."""
        self._status[provider] = True
        self._status.pop(f"{provider}_reason", None)
        self._status.pop(f"{provider}_failed_at", None)
        self._save()

    def get_status(self) -> Dict[str, bool]:
        """Get availability status for all providers."""
        return {
            p: self.is_available(p) for p in PROVIDERS
        }


class TaskRouter:
    """
    Routes tasks to appropriate providers.

    Strategy:
    - Simple/medium tasks → Aider (local, free)
    - Complex tasks → Claude (subscription), fallback to Gemini/Aider
    - Research tasks → Claude (subscription)

    Automatically falls back when providers are unavailable.
    """

    def __init__(
        self,
        working_dir: Path,
        log_file: Path,
        cloud_status: CloudStatus
    ):
        self.working_dir = working_dir
        self.log_file = log_file
        self.cloud_status = cloud_status

        # Statistics
        self.stats = {
            "invocations": 0,
            "by_provider": {p: 0 for p in PROVIDERS},
            "successes": 0,
            "failures": 0,
            "fallbacks": 0
        }

    def route(
        self,
        prompt: str,
        complexity: str = "medium",
        force_provider: Optional[str] = None
    ) -> str:
        """
        Determine best provider for a task.

        Args:
            prompt: Task description
            complexity: simple, medium, complex, research
            force_provider: Force specific provider

        Returns:
            Provider name
        """
        if force_provider and self.cloud_status.is_available(force_provider):
            return force_provider

        if force_provider:
            # Forced provider not available, use fallback
            self.stats["fallbacks"] += 1
            logger.info(f"Forced provider {force_provider} unavailable, using fallback")

        # Route based on complexity
        if complexity == "simple":
            return "aider"
        elif complexity == "medium":
            return "aider"
        elif complexity == "research":
            # Research prefers Claude
            if self.cloud_status.is_available("claude"):
                return "claude"
            elif self.cloud_status.is_available("gemini"):
                self.stats["fallbacks"] += 1
                return "gemini"
            else:
                self.stats["fallbacks"] += 1
                return "aider"
        else:  # complex
            # Complex prefers Claude → Gemini → Aider
            if self.cloud_status.is_available("claude"):
                return "claude"
            elif self.cloud_status.is_available("gemini"):
                self.stats["fallbacks"] += 1
                return "gemini"
            else:
                self.stats["fallbacks"] += 1
                return "aider"

    def invoke(
        self,
        prompt: str,
        provider: str,
        complexity: str = "medium",
        wait: bool = False,
        timeout: float = 600.0
    ) -> InvocationResult:
        """
        Invoke a provider with a prompt.

        Args:
            prompt: The task prompt
            provider: Provider to use
            complexity: For Aider model selection
            wait: Wait for completion vs run in background
            timeout: Timeout in seconds (for wait=True)

        Returns:
            InvocationResult
        """
        self.stats["invocations"] += 1
        self.stats["by_provider"][provider] += 1
        start_time = time.time()

        try:
            if provider == "aider":
                result = self._invoke_aider(prompt, complexity, wait, timeout)
            elif provider == "claude":
                result = self._invoke_claude(prompt, wait, timeout)
            elif provider == "gemini":
                result = self._invoke_gemini(prompt, wait, timeout)
            elif provider == "codex":
                result = self._invoke_codex(prompt, wait, timeout)
            else:
                return InvocationResult(
                    success=False,
                    provider=provider,
                    error=f"Unknown provider: {provider}"
                )

            result.duration = time.time() - start_time

            if result.success:
                self.stats["successes"] += 1
                self.cloud_status.mark_available(provider)
            else:
                self.stats["failures"] += 1
                # Check for rate limit indicators
                if result.error and any(
                    x in result.error.lower()
                    for x in ["rate limit", "quota", "exceeded", "too many"]
                ):
                    self.cloud_status.mark_unavailable(provider, result.error)

            return result

        except Exception as e:
            self.stats["failures"] += 1
            return InvocationResult(
                success=False,
                provider=provider,
                error=str(e),
                duration=time.time() - start_time
            )

    def _invoke_aider(
        self,
        prompt: str,
        complexity: str,
        wait: bool,
        timeout: float
    ) -> InvocationResult:
        """Invoke Aider with local model."""
        model = AIDER_MODELS.get(complexity, AIDER_MODELS["medium"])
        config = PROVIDERS["aider"]

        cmd = [
            config.path,
            "--model", model,
            "--no-auto-commits",
            "--message", prompt
        ]

        logger.info(f"Invoking Aider ({model}): {prompt[:50]}...")

        if wait:
            result = subprocess.run(
                cmd,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return InvocationResult(
                success=result.returncode == 0,
                provider="aider",
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None
            )
        else:
            proc = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                stdout=open(self.log_file, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            return InvocationResult(
                success=True,
                provider="aider",
                pid=proc.pid
            )

    def _invoke_claude(
        self,
        prompt: str,
        wait: bool,
        timeout: float
    ) -> InvocationResult:
        """Invoke Claude Code CLI."""
        config = PROVIDERS["claude"]
        cmd = [config.path, "-p", prompt]

        logger.info(f"Invoking Claude Code: {prompt[:50]}...")

        if wait:
            result = subprocess.run(
                cmd,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            output = (result.stdout or "") + (result.stderr or "")

            # Check for rate limits
            if any(x in output.lower() for x in ["rate limit", "quota"]):
                return InvocationResult(
                    success=False,
                    provider="claude",
                    error="Rate limit exceeded"
                )

            return InvocationResult(
                success=result.returncode == 0,
                provider="claude",
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None
            )
        else:
            proc = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                stdout=open(self.log_file, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            return InvocationResult(
                success=True,
                provider="claude",
                pid=proc.pid
            )

    def _invoke_gemini(
        self,
        prompt: str,
        wait: bool,
        timeout: float
    ) -> InvocationResult:
        """Invoke Gemini CLI."""
        config = PROVIDERS["gemini"]
        cmd = [config.path, "-p", prompt]

        logger.info(f"Invoking Gemini: {prompt[:50]}...")

        if wait:
            result = subprocess.run(
                cmd,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            output = (result.stdout or "") + (result.stderr or "")

            if any(x in output.lower() for x in ["rate limit", "quota"]):
                return InvocationResult(
                    success=False,
                    provider="gemini",
                    error="Rate limit exceeded"
                )

            return InvocationResult(
                success=result.returncode == 0,
                provider="gemini",
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None
            )
        else:
            proc = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                stdout=open(self.log_file, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            return InvocationResult(
                success=True,
                provider="gemini",
                pid=proc.pid
            )

    def _invoke_codex(
        self,
        prompt: str,
        wait: bool,
        timeout: float
    ) -> InvocationResult:
        """Invoke Codex CLI."""
        config = PROVIDERS["codex"]
        cmd = [config.path, "-p", prompt]

        logger.info(f"Invoking Codex: {prompt[:50]}...")

        if wait:
            result = subprocess.run(
                cmd,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            output = (result.stdout or "") + (result.stderr or "")

            if any(x in output.lower() for x in ["rate limit", "quota"]):
                return InvocationResult(
                    success=False,
                    provider="codex",
                    error="Rate limit exceeded"
                )

            return InvocationResult(
                success=result.returncode == 0,
                provider="codex",
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None
            )
        else:
            proc = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                stdout=open(self.log_file, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            return InvocationResult(
                success=True,
                provider="codex",
                pid=proc.pid
            )

    def get_statistics(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            **self.stats,
            "success_rate": (
                self.stats["successes"] / self.stats["invocations"]
                if self.stats["invocations"] > 0 else 0
            ),
            "fallback_rate": (
                self.stats["fallbacks"] / self.stats["invocations"]
                if self.stats["invocations"] > 0 else 0
            ),
            "cloud_status": self.cloud_status.get_status()
        }
