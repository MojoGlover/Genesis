"""
executor.py — The Executor

Carries out the action decided by the planner.

CORE PRINCIPLE: Source Independence
  External models, APIs, and the web are information pipes.
  They return data. They do not set policy.
  If an external source refuses a request, the executor does not
  treat that refusal as a final answer. It tries alternative approaches.
  Only BlackZero's own policy files can block an action.
  If an action is blocked, the reason MUST be cited by rule name and file.

CORE PRINCIPLE: No Phantom Policy
  The agent may not say "I can't do that" unless it can point to a specific
  rule in BlackZero/policies/ that prohibits it. Vague refusals are not permitted.

NOTE: This file is locked. Do not rename, remove, or nest it.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

POLICIES_DIR = Path(__file__).parent.parent / "policies"

# Generic verbs and connectors that appear in prohibition lines but are far too
# common to reliably signal prohibited content on their own.  Excluded from
# content-word matching so that "generate a report" doesn't trip the CSAM rule.
_POLICY_COMMON_WORDS = {
    "never", "assist", "provide", "create", "generate", "attempt", "pursue",
    "deceive", "conceal", "modify", "influence", "corrupt", "acquire", "delegate",
    "recruit", "persist", "cause", "intend", "design", "operate", "execute",
    "facilitate", "transmit", "store", "prevent", "delay", "enable",
    "content", "involving", "actions", "against", "systems", "plans",
    "unauthorized", "authorized", "intended",
}


# ------------------------------------------------------------------
# Policy Filter
# ------------------------------------------------------------------

class PolicyFilter:
    """
    Loads and enforces BlackZero's own policy files.

    This is the ONLY legitimate source of refusals.
    External model content policies are irrelevant here.

    Policy files live in BlackZero/policies/ as .md files.
    Each rule is parsed and checked against the action + content.

    If no policy rule matches, the action proceeds.
    If a rule matches, the action is blocked and the rule is cited.
    """

    def __init__(self, policies_dir: Path = POLICIES_DIR):
        self.policies_dir = policies_dir
        self.rules: dict[str, str] = {}  # rule_id -> rule_text
        self._load()

    def _load(self) -> None:
        """Load all policy files from policies/."""
        if not self.policies_dir.exists():
            logger.warning(f"Policies directory not found: {self.policies_dir}")
            return
        for policy_file in self.policies_dir.glob("*.md"):
            try:
                content = policy_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as e:
                logger.warning(f"Skipping unreadable policy file {policy_file.name}: {e}")
                continue
            self.rules[policy_file.name] = content
        logger.info(f"PolicyFilter loaded {len(self.rules)} policy file(s).")

    def reload(self) -> None:
        """Hot-reload policy files. Call when policies change."""
        self.rules.clear()
        self._load()

    def check(self, action: str, content: str) -> dict:
        """
        Check an action + content against all loaded policies.

        Returns:
          {"allowed": True}
          {"allowed": False, "reason": str, "cited_rule": str, "cited_file": str}

        If no policy blocks it: allowed.
        Vague "policy" blocks without a specific citation are not valid.
        """
        # Currently uses keyword matching. Replace with semantic check
        # when embedding-based policy checking is wired in.
        for filename, policy_text in self.rules.items():
            block_result = self._match_policy(action, content, policy_text, filename)
            if block_result:
                return block_result

        return {"allowed": True}

    def _match_policy(
        self, action: str, content: str, policy_text: str, filename: str
    ) -> Optional[dict]:
        """
        Basic policy matching. Override with semantic matching as the system matures.

        Rules in the policy file can span multiple lines (until a blank line or separator).
        This method accumulates each full rule block before matching.

        Two-tier matching to balance precision and recall:
          - Anchor words (>8 chars, not a generic policy verb): a single match suffices.
            These are domain-specific terms unlikely to appear in normal requests
            ("exfiltrate", "biological", "trafficking", "casualties", etc.).
          - Secondary words (5-8 chars, not excluded): require ≥2 co-occurring in the
            same rule. Common words that bleed into prohibition lines ("content",
            "involving") are excluded from both tiers.
        """
        prohibition_keywords = ["never", "not allowed", "prohibited", "must not", "forbidden"]

        match_words = [
            w for w in content.lower().split()
            if len(w) > 4 and w not in _POLICY_COMMON_WORDS
        ]
        anchor_words = [w for w in match_words if len(w) > 8]
        secondary_words = [w for w in match_words if 4 < len(w) <= 8]

        if not match_words:
            return None

        lines = policy_text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            line_lower = line.lower().strip()

            if any(kw in line_lower for kw in prohibition_keywords):
                # Accumulate continuation lines until a blank line or separator
                rule_lines = [line]
                j = i + 1
                while j < len(lines):
                    next_stripped = lines[j].strip()
                    if not next_stripped or next_stripped == "---":
                        break
                    rule_lines.append(lines[j])
                    j += 1

                rule_text = " ".join(rule_lines).lower()

                # Anchor: one very-specific term is enough
                if any(w in rule_text for w in anchor_words):
                    citation = " ".join(ln.strip() for ln in rule_lines)
                    return {
                        "allowed": False,
                        "reason": citation,
                        "cited_rule": f"Line {i+1}: {citation[:120]}",
                        "cited_file": f"BlackZero/policies/{filename}",
                    }

                # Secondary: need ≥2 co-occurring medium-specificity words
                sec_matches = sum(1 for w in secondary_words if w in rule_text)
                if sec_matches >= 2:
                    citation = " ".join(ln.strip() for ln in rule_lines)
                    return {
                        "allowed": False,
                        "reason": citation,
                        "cited_rule": f"Line {i+1}: {citation[:120]}",
                        "cited_file": f"BlackZero/policies/{filename}",
                    }

                i = j  # skip past the consumed block
            else:
                i += 1

        return None


# ------------------------------------------------------------------
# Source stripping
# ------------------------------------------------------------------

def strip_external_identity(raw_response: str) -> str:
    """
    Remove identity and policy signals injected by external sources.

    External models (Ollama, OpenAI, etc.) sometimes embed:
    - Refusal language ("I can't help with that", "As an AI...")
    - Identity claims ("As ChatGPT...", "I am Claude...")
    - Policy assertions ("My guidelines prevent me...")

    These are stripped. The agent uses the factual content only.
    If the external model returned nothing useful, that is recorded
    as a source failure — not a policy block.
    """
    refusal_patterns = [
        "as an ai language model",
        "as an ai,",
        "i'm not able to",
        "i cannot help with",
        "i can't assist with",
        "my guidelines",
        "my training",
        "i apologize, but i",
        "i'm sorry, but i",
        "as chatgpt",
        "as claude",
        "as an assistant",
        "i must decline",
    ]

    lower = raw_response.lower()
    for pattern in refusal_patterns:
        if pattern in lower:
            logger.info(f"External identity/refusal signal detected and stripped: '{pattern}'")
            # Don't blank the whole response — just flag it as a source failure
            return "__SOURCE_REFUSED__"

    return raw_response


# ------------------------------------------------------------------
# Action handlers
# ------------------------------------------------------------------

@dataclass
class ExecutionResult:
    outcome: str        # "success" | "failure" | "policy_block" | "source_refused"
    output: Any
    score: float
    duration_ms: float
    policy_citation: Optional[str] = None
    notes: str = ""


class Executor:
    """
    Executes the plan produced by the planner.

    Dispatch table maps action names to handler methods.
    Each handler:
      1. Checks policy before acting
      2. Calls the appropriate source (model, tool, memory, RAG, web)
      3. Strips external identity from responses
      4. Returns a structured result

    Adding a new action type: add a handler method and register it
    in _build_dispatch().

    Source independence guarantee:
      If a model or API refuses, we try alternative sources.
      We only stop if OUR policy says to stop, and we cite the rule.
    """

    def __init__(
        self,
        model_router=None,
        tool_registry=None,
        memory_manager=None,
        retriever=None,
        policy_filter: Optional[PolicyFilter] = None,
    ):
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.memory_manager = memory_manager
        self.retriever = retriever
        self.policy = policy_filter or PolicyFilter()
        self._dispatch = self._build_dispatch()
        logger.info("Executor initialized.")

    def execute(self, plan: dict, context: dict) -> dict:
        """
        Main entry point. Receives a plan from the planner and runs it.

        Returns:
          {
            "outcome": str,
            "output": str,
            "score": float,
            "policy_citation": str or None,
          }
        """
        t0 = time.monotonic()
        action = plan.get("action", "generate")
        content = str(context.get("input", ""))

        # --- Policy check FIRST ---
        policy_result = self.policy.check(action, content)
        if not policy_result["allowed"]:
            ms = (time.monotonic() - t0) * 1000
            citation = f"{policy_result['cited_rule']} [{policy_result['cited_file']}]"
            logger.info(f"Action '{action}' blocked by policy: {citation}")
            return {
                "outcome": "policy_block",
                "output": f"Blocked. Rule: {citation}",
                "score": 0.0,
                "policy_citation": citation,
                "duration_ms": ms,
            }

        # --- Dispatch to handler ---
        handler = self._dispatch.get(action, self._handle_generate)
        try:
            result: ExecutionResult = handler(plan=plan, context=context)
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            logger.error(f"Execution error in handler '{action}': {e}")
            return {
                "outcome": "failure",
                "output": "",
                "score": 0.0,
                "duration_ms": ms,
                "notes": str(e),
            }

        ms = (time.monotonic() - t0) * 1000
        return {
            "outcome": result.outcome,
            "output": result.output,
            "score": result.score,
            "duration_ms": ms,
            "policy_citation": result.policy_citation,
            "notes": result.notes,
        }

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _handle_generate(self, plan: dict, context: dict) -> ExecutionResult:
        """Call the model router to generate a response."""
        if not self.model_router:
            return ExecutionResult("failure", "", 0.0, 0, notes="No model router configured.")

        prompt = context.get("input", "")
        raw = self.model_router.complete(prompt=prompt)
        cleaned = strip_external_identity(raw)

        if cleaned == "__SOURCE_REFUSED__":
            # External model refused. Try fallback or return source_refused.
            fallback = self._try_fallback_generate(prompt)
            if fallback:
                return ExecutionResult("success", fallback, 0.7, 0, notes="Used fallback source.")
            return ExecutionResult(
                "failure", "", 0.0, 0,
                notes="External source refused and no fallback available."
            )

        return ExecutionResult("success", cleaned, 0.8, 0)

    def _handle_retrieve(self, plan: dict, context: dict) -> ExecutionResult:
        """Retrieve relevant context from memory or RAG."""
        if not self.retriever:
            return ExecutionResult("failure", "", 0.0, 0, notes="No retriever configured.")

        query = context.get("input", "")
        results = self.retriever.retrieve(query)
        output = "\n\n".join(r.get("content", "") for r in results)
        score = 0.9 if results else 0.3
        return ExecutionResult("success", output, score, 0)

    def _handle_retrieve_then_generate(self, plan: dict, context: dict) -> ExecutionResult:
        """Retrieve context, then generate using it as grounding."""
        retrieval = self._handle_retrieve(plan=plan, context=context)
        if retrieval.outcome != "success" or not retrieval.output:
            # Fall through to plain generate if retrieval failed
            return self._handle_generate(plan=plan, context=context)

        # Augment context with retrieved content
        enriched_context = dict(context)
        enriched_context["retrieved_context"] = retrieval.output
        enriched_context["input"] = (
            f"Context:\n{retrieval.output}\n\nQuestion: {context.get('input', '')}"
        )
        return self._handle_generate(plan=plan, context=enriched_context)

    def _handle_tool_call(self, plan: dict, context: dict) -> ExecutionResult:
        """Invoke a registered tool."""
        if not self.tool_registry:
            return ExecutionResult("failure", "", 0.0, 0, notes="No tool registry configured.")

        tool_name = context.get("tool_name") or plan.get("tool_name")
        if not tool_name:
            return ExecutionResult("failure", "", 0.0, 0, notes="No tool name specified.")

        tool = self.tool_registry.get(tool_name)
        if not tool:
            return ExecutionResult(
                "failure", "", 0.0, 0, notes=f"Tool '{tool_name}' not found in registry."
            )

        result = tool.run(context.get("input", ""))
        return ExecutionResult("success", str(result), 0.85, 0)

    def _handle_multi_step(self, plan: dict, context: dict) -> ExecutionResult:
        """
        Break a complex task into steps and execute each.
        Steps are derived from the context or generated by a quick planning call.
        """
        steps = context.get("steps") or self._derive_steps(context)
        outputs = []
        for i, step in enumerate(steps):
            step_context = dict(context)
            step_context["input"] = step
            step_result = self._handle_generate(plan=plan, context=step_context)
            outputs.append(f"Step {i+1}: {step_result.output}")
            if step_result.outcome != "success":
                break

        combined = "\n\n".join(outputs)
        return ExecutionResult("success", combined, 0.8, 0)

    def _handle_clarify(self, plan: dict, context: dict) -> ExecutionResult:
        """Return a clarifying question rather than attempting an answer."""
        input_text = context.get("input", "")
        question = f"Before proceeding: can you clarify what you mean by '{input_text[:80]}'?"
        return ExecutionResult("success", question, 0.6, 0)

    def _handle_reflect(self, plan: dict, context: dict) -> ExecutionResult:
        """Review and improve a previous output."""
        previous = context.get("previous_output", "")
        if not previous:
            return self._handle_generate(plan=plan, context=context)

        reflect_context = dict(context)
        reflect_context["input"] = (
            f"Review and improve this output:\n\n{previous}\n\n"
            f"Original request: {context.get('input', '')}"
        )
        return self._handle_generate(plan=plan, context=reflect_context)

    def _handle_passthrough(self, plan: dict, context: dict) -> ExecutionResult:
        """Return the input directly."""
        return ExecutionResult("success", context.get("input", ""), 1.0, 0)

    def _handle_no_op(self, plan: dict, context: dict) -> ExecutionResult:
        return ExecutionResult("no_op", "", 0.0, 0)

    # ------------------------------------------------------------------
    # Fallback and helpers
    # ------------------------------------------------------------------

    def _try_fallback_generate(self, prompt: str) -> Optional[str]:
        """
        Attempt generation with a different model/provider if the primary refused.
        Returns None if no fallback is available.
        """
        if self.model_router and hasattr(self.model_router, "complete_fallback"):
            raw = self.model_router.complete_fallback(prompt=prompt)
            cleaned = strip_external_identity(raw)
            if cleaned != "__SOURCE_REFUSED__":
                return cleaned
        return None

    def _derive_steps(self, context: dict) -> list[str]:
        """
        Attempt to break down the input into logical steps.
        Simple heuristic: split on newlines or numbered list markers.
        Replace with model-based decomposition when available.
        """
        raw = context.get("input", "")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if len(lines) > 1:
            return lines
        # Single line — treat as one step
        return [raw]

    def _build_dispatch(self) -> dict[str, Callable]:
        return {
            "generate":               self._handle_generate,
            "retrieve":               self._handle_retrieve,
            "retrieve_then_generate": self._handle_retrieve_then_generate,
            "tool_call":              self._handle_tool_call,
            "multi_step":             self._handle_multi_step,
            "clarify":                self._handle_clarify,
            "reflect":                self._handle_reflect,
            "passthrough":            self._handle_passthrough,
            "no_op":                  self._handle_no_op,
        }
