"""
Engineer0 Local Brain

Ollama-based reasoning for Engineer0's internal decision-making.
Never uses cloud credits - runs entirely on local hardware.
"""

from __future__ import annotations
import json
import logging
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

OLLAMA_API = "http://localhost:11434/api"


@dataclass
class ReasoningResult:
    """Result from local reasoning."""
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None
    tokens_used: int = 0


class LocalBrain:
    """
    Ollama-based local reasoning for Engineer0.

    She uses this for:
    - Deciding what to work on next
    - Classifying task complexity
    - Analyzing failures and planning retries
    - Summarizing progress
    - Making routing decisions

    All reasoning happens locally - no cloud credits consumed.
    """

    def __init__(
        self,
        reasoning_model: str = "llama3.1:70b",
        fast_model: str = "codellama:13b",
        timeout: float = 120.0
    ):
        self.reasoning_model = reasoning_model
        self.fast_model = fast_model
        self.timeout = timeout
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        if self._available is not None:
            return self._available

        try:
            req = urllib.request.Request(f"{OLLAMA_API}/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False

        return self._available

    def get_available_models(self) -> List[str]:
        """Get list of available Ollama models."""
        try:
            req = urllib.request.Request(f"{OLLAMA_API}/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def reason(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7
    ) -> ReasoningResult:
        """
        Use local model for reasoning.

        Args:
            prompt: The reasoning prompt
            model: Model to use (defaults to reasoning_model)
            system: Optional system prompt
            temperature: Sampling temperature

        Returns:
            ReasoningResult with response or error
        """
        if not self.is_available():
            return ReasoningResult(
                success=False,
                error="Ollama not available"
            )

        model = model or self.reasoning_model

        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature}
            }

            if system:
                payload["system"] = system

            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{OLLAMA_API}/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode())
                return ReasoningResult(
                    success=True,
                    response=result.get("response", "").strip(),
                    model=model,
                    tokens_used=result.get("eval_count", 0)
                )

        except urllib.error.URLError as e:
            return ReasoningResult(success=False, error=f"Connection error: {e}")
        except TimeoutError:
            return ReasoningResult(success=False, error="Timeout")
        except Exception as e:
            return ReasoningResult(success=False, error=str(e))

    def quick_reason(self, prompt: str) -> ReasoningResult:
        """Use fast model for quick reasoning."""
        return self.reason(prompt, model=self.fast_model, temperature=0.3)

    def classify_complexity(self, task_description: str) -> str:
        """
        Classify task complexity: simple, medium, complex, or research.

        Uses fast model for efficiency.
        """
        prompt = f"""Classify this task's complexity. Reply with ONLY one word: simple, medium, complex, or research.

Task: {task_description}

Classification:"""

        result = self.quick_reason(prompt)

        if result.success and result.response:
            response = result.response.lower().strip()
            if "simple" in response:
                return "simple"
            elif "complex" in response:
                return "complex"
            elif "research" in response:
                return "research"

        return "medium"  # Default

    def decide_next_action(
        self,
        pending_tasks: List[Dict[str, Any]],
        recent_history: List[Dict[str, Any]],
        current_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Decide what Engineer0 should do next.

        Returns:
            Dict with action recommendation
        """
        prompt = f"""You are Engineer0, an autonomous AI supervisor.

Current State:
- Pending tasks: {len(pending_tasks)}
- Recent completions: {len([h for h in recent_history if h.get('status') == 'completed'])}
- Recent failures: {len([h for h in recent_history if h.get('status') == 'failed'])}
- Cloud status: {current_state.get('cloud_status', 'unknown')}

Pending Tasks (top 5):
{json.dumps(pending_tasks[:5], indent=2) if pending_tasks else 'None'}

Recent History (last 3):
{json.dumps(recent_history[-3:], indent=2) if recent_history else 'None'}

What should I do next? Consider:
1. Are there high-priority tasks waiting?
2. Should I retry any failed tasks?
3. Is there a pattern in failures I should address?
4. Should I wait for user input?

Reply in JSON format:
{{"action": "process_task|wait|analyze_failures|request_input", "reason": "...", "task_id": "..." (if applicable)}}"""

        result = self.reason(prompt, temperature=0.3)

        if result.success and result.response:
            try:
                # Try to parse JSON from response
                response = result.response
                # Handle markdown code blocks
                if "```" in response:
                    response = response.split("```")[1]
                    if response.startswith("json"):
                        response = response[4:]
                return json.loads(response.strip())
            except json.JSONDecodeError:
                pass

        # Default action
        return {"action": "process_task", "reason": "Default: process next task"}

    def analyze_failure(
        self,
        task_description: str,
        error: str,
        retry_count: int
    ) -> Dict[str, Any]:
        """
        Analyze a task failure and recommend action.

        Returns:
            Dict with retry recommendation and strategy
        """
        prompt = f"""Analyze this task failure:

Task: {task_description}
Error: {error}
Retry count: {retry_count}/3

Should we:
1. Retry with same approach?
2. Retry with different provider?
3. Break into smaller tasks?
4. Mark as permanently failed?

Reply in JSON format:
{{"should_retry": true/false, "strategy": "same|different_provider|break_down|fail", "reason": "...", "suggested_provider": "aider|claude|gemini" (if different_provider)}}"""

        result = self.quick_reason(prompt)

        if result.success and result.response:
            try:
                response = result.response
                if "```" in response:
                    response = response.split("```")[1]
                    if response.startswith("json"):
                        response = response[4:]
                return json.loads(response.strip())
            except json.JSONDecodeError:
                pass

        # Default: retry with same approach if retries remaining
        return {
            "should_retry": retry_count < 3,
            "strategy": "same",
            "reason": "Default retry strategy"
        }

    def summarize_session(
        self,
        tasks_completed: int,
        tasks_failed: int,
        duration_minutes: float,
        notable_events: List[str]
    ) -> str:
        """Generate a session summary."""
        prompt = f"""Summarize this work session as Engineer0:

- Tasks completed: {tasks_completed}
- Tasks failed: {tasks_failed}
- Duration: {duration_minutes:.1f} minutes
- Notable events: {', '.join(notable_events) if notable_events else 'None'}

Write a brief 2-3 sentence summary suitable for logging."""

        result = self.quick_reason(prompt)

        if result.success and result.response:
            return result.response

        return f"Session: {tasks_completed} completed, {tasks_failed} failed in {duration_minutes:.1f} min."

    def select_provider(
        self,
        task_description: str,
        complexity: str,
        cloud_status: Dict[str, bool]
    ) -> str:
        """
        Select the best provider for a task.

        Falls back through providers based on availability.
        """
        # Check what's available
        available = [p for p, status in cloud_status.items() if status is not False]

        if not available:
            return "aider"  # Always available (local)

        # Simple/medium tasks: prefer local (free)
        if complexity in ["simple", "medium"]:
            return "aider"

        # Complex/research: prefer Claude, fall back through chain
        preference_order = ["claude", "gemini", "codex", "aider"]

        for provider in preference_order:
            if provider in available or cloud_status.get(provider) is not False:
                return provider

        return "aider"  # Final fallback
