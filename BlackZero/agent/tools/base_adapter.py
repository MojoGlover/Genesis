"""
base_adapter.py — Capability adapter protocol for BlackZero v2.

Every tool, API wrapper, and external connector should implement this protocol.
The tool bus calls validate → execute → normalize in sequence.

Rules:
  - Adapters do not decide policy (that is the policy gate's job).
  - Adapters do not choose themselves (that is the router's job).
  - Adapters do not write to long-term memory (that is the evidence ledger's job).
  - Adapters fail loudly with structured errors — never silent None returns.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    @classmethod
    def passed(cls) -> "ValidationResult":
        return cls(ok=True)

    @classmethod
    def failed(cls, *errors: str) -> "ValidationResult":
        return cls(ok=False, errors=list(errors))


@dataclass
class ExecutionResult:
    ok: bool
    raw_output: Any
    side_effects: str = "none"      # none | local | remote | destructive | financial | public
    duration_ms: float = 0.0
    error: str | None = None

    @classmethod
    def success(cls, raw_output: Any, side_effects: str = "none",
                duration_ms: float = 0.0) -> "ExecutionResult":
        return cls(ok=True, raw_output=raw_output,
                   side_effects=side_effects, duration_ms=duration_ms)

    @classmethod
    def failure(cls, error: str, duration_ms: float = 0.0) -> "ExecutionResult":
        return cls(ok=False, raw_output=None, error=error, duration_ms=duration_ms)


@dataclass
class NormalizedResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    usable_for_claims: bool = True
    error: str | None = None

    def to_tool_output(self) -> str:
        """Render as a string for injection into LangGraph tool messages."""
        if not self.ok:
            return f"ERROR: {self.error}"
        lines = [self.summary]
        for k, v in self.data.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)


@dataclass
class ExecutionContext:
    agent_id: str
    mode: str = "act"              # explore | plan | act | repair | audit | quarantine
    session_id: str = ""
    dry_run: bool = False


# ── Adapter base class ────────────────────────────────────────────────────────

class CapabilityAdapter:
    """
    Base class for all BlackZero capability adapters.

    Subclass this and implement validate(), execute(), normalize().
    The tool bus calls these in sequence — do not override __call__.
    """

    id: str = ""   # must match the adapter field in the capability manifest

    def validate(self, input: dict) -> ValidationResult:
        """
        Check that input contains all required fields with valid values.
        Return ValidationResult.failed(...) with specific error messages.
        Never raise from validate — return a failed result instead.
        """
        return ValidationResult.passed()

    def execute(self, input: dict, context: ExecutionContext) -> ExecutionResult:
        """
        Perform the capability. Return ExecutionResult.
        Record timing, side effects, and raw output.
        May raise AdapterError for unrecoverable failures.
        """
        raise NotImplementedError(f"{self.__class__.__name__}.execute() not implemented")

    def normalize(self, raw: ExecutionResult) -> NormalizedResult:
        """
        Turn the raw ExecutionResult into a stable NormalizedResult.
        The brain reads NormalizedResult — it never sees raw_output directly.
        """
        if not raw.ok:
            return NormalizedResult(ok=False, summary="", error=raw.error,
                                    usable_for_claims=False)
        return NormalizedResult(
            ok=True,
            summary=str(raw.raw_output)[:500],
            data=raw.raw_output if isinstance(raw.raw_output, dict) else {"output": raw.raw_output},
        )

    def run_full(self, input: dict, context: ExecutionContext) -> NormalizedResult:
        """
        Convenience: validate → execute → normalize in one call.
        The tool bus uses this. Adapters do not call this themselves.
        """
        validation = self.validate(input)
        if not validation.ok:
            return NormalizedResult(ok=False, summary="",
                                    error=f"Validation failed: {'; '.join(validation.errors)}",
                                    usable_for_claims=False)
        t0 = time.monotonic()
        try:
            result = self.execute(input, context)
        except Exception as e:
            return NormalizedResult(ok=False, summary="",
                                    error=f"Execution error: {e}",
                                    usable_for_claims=False)
        result.duration_ms = (time.monotonic() - t0) * 1000
        return self.normalize(result)


class AdapterError(Exception):
    """Raised by adapters for unrecoverable, structured failures."""
