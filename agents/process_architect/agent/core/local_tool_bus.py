"""
agent/core/local_tool_bus.py — Local execution bus for BlackZero v2.

The only path between the brain and tool execution. Replaces direct calls to
build_executor() in the tool node.

Flow for every tool call:
  1. Route — look up manifest, check lifecycle and mode
  2. Quarantine check — block if runtime-quarantined (unless repair mode)
  3. Policy check — ask policy gate (fail-open: down = allow)
  4. Execute — call the underlying executor function
  5. Normalize — wrap raw string result in a NormalizedResult
  6. Record — update quarantine overlay + append to evidence ledger
  7. Return — (result_str, NormalizedResult) to the tool node

The tool node becomes dumb: it just calls local_tool_bus.execute() and puts
result_str in tool_history. All routing, policy, quarantine, and evidence logic
lives here.

Third Pass additions:
  - mode is threaded from graph state into routing and quarantine checks
  - QuarantineOverlay tracks consecutive failures; blocks at threshold
  - repair mode bypasses quarantine so capabilities can self-heal
  - Successful executions reset the consecutive-failure count
"""
from __future__ import annotations

import logging
import time
from typing import Callable, TYPE_CHECKING

from agent.tools.base_adapter import NormalizedResult, ExecutionContext

if TYPE_CHECKING:
    from agent.core.router           import CapabilityRouter
    from agent.core.quarantine       import QuarantineOverlay
    from agent.core.satellite_router import SatelliteRouter
    from agent.modules.evidence      import EvidenceLedger
    from agent.modules.policy        import PolicyClient

logger = logging.getLogger(__name__)

# Result strings longer than this are truncated before the LLM sees them.
_MAX_RESULT_LEN = 8000

# ── Origin-based execution gate ─────────────────────────────────────────────
# Audit finding 2026-07-14 (Engineer0 hallucination/spoofing audit): tool
# execution had NO concept of who/what asked for it — the policy check below
# (step 3) only ever looked at the tool name, never the caller. Combined with
# `from_agent` defaulting to "user" everywhere upstream, anything that could
# reach the chat endpoint (including another agent, or an automated test
# harness) got full tool authority indistinguishable from a real instruction
# from Darnie.
#
# TRUSTED_ORIGINS are the only `from_agent`/origin values allowed to invoke a
# HIGH_RISK_TOOL. This is NOT the same question as "is this a real human" —
# task_loop and todo_loop are legitimate autonomous work Engineer0 is scoped
# to do without per-action confirmation (config.yaml autonomy_level). What's
# excluded is everything else: unverified/omitted origin, and raw agent-to-
# agent chat turns that never went through the reviewed task queue.
TRUSTED_ORIGINS = frozenset({"user", "loop:task_loop", "loop:todo_loop"})

# Tools whose side effects are hard or impossible to undo, or that reach
# outside this agent's own sandbox (git history, the filesystem, a shell,
# a physical device, credential grants). Extend this set in the template,
# not per-agent, if a new tool with real side effects is added.
HIGH_RISK_TOOLS = frozenset({
    "shell", "python",
    "write_file", "patch_file",
    "git_add", "git_commit", "git_push",
    "adb",
    "assign_api", "revoke_api",
    # Added 2026-07-17 deep audit: web_browser was fully built (real
    # Playwright automation, including a signup action that submits real
    # forms and can create real accounts) but had never been wired into the
    # dispatch table at all, so it never went through this gate either.
    "web_browser",
})


class LocalToolBus:
    """
    Wires router → quarantine → policy → executor → evidence into a single call.

    Constructed once in build_graph() and passed to make_tool_node().
    Thread-safe: all state is read-only after construction except QuarantineOverlay
    (which serializes its writes via file I/O).
    """

    def __init__(
        self,
        executor_fn:      Callable[[str, dict], str],
        router:           "CapabilityRouter",
        policy:           "PolicyClient",
        evidence:         "EvidenceLedger",
        quarantine:       "QuarantineOverlay | None"  = None,
        satellite_router: "SatelliteRouter | None"    = None,
    ) -> None:
        self._executor         = executor_fn
        self._router           = router
        self._policy           = policy
        self._evidence         = evidence
        self._quarantine       = quarantine
        self._satellite_router = satellite_router

    def execute(
        self,
        tool_name:  str,
        params:     dict,
        session_id: str = "",
        mode:       str = "act",
        origin:     str = "unverified",
    ) -> tuple[str, NormalizedResult]:
        """
        Execute a tool call end-to-end.

        origin is the caller's `from_agent`/provenance value (see graph.py's
        recall node and TRUSTED_ORIGINS above). Fail-closed default:
        "unverified" — never assume trust when a caller forgets to pass it.

        Returns:
            (result_str, normalized_result)
            result_str   — formatted string for LLM tool_history
            normalized   — structured result stored in evidence ledger
        """
        context = ExecutionContext(
            agent_id=origin,
            mode=mode,
            session_id=session_id,
        )

        # ── 0. Origin gate ────────────────────────────────────────────────────
        # Runs before routing/quarantine/policy — a spoofed or unverified
        # caller should never even reach the policy client, let alone the
        # executor. See TRUSTED_ORIGINS/HIGH_RISK_TOOLS above.
        if tool_name in HIGH_RISK_TOOLS and origin not in TRUSTED_ORIGINS:
            msg = (
                f"Origin '{origin}' is not authorized to call high-risk tool "
                f"'{tool_name}'. Requires one of: {sorted(TRUSTED_ORIGINS)}."
            )
            logger.warning("[tool_bus] %s: origin denied (origin=%s)", tool_name, origin)
            self._evidence.record_result(
                capability_id=f"tool.unverified.{tool_name}",
                input_summary=f"{tool_name}({list(params.keys())})",
                output_summary=msg,
                status="origin_denied",
                session_id=session_id,
                usable_for_claims=False,
                error=msg,
                origin=origin,
            )
            return msg, NormalizedResult(ok=False, summary=msg, error=msg, usable_for_claims=False)

        # ── 1. Route ──────────────────────────────────────────────────────────
        decision = self._router.resolve_tool(tool_name, mode=mode)
        if not decision.routable:
            msg = f"Routing blocked: {decision.reason}"
            logger.warning("[tool_bus] %s: %s", tool_name, msg)
            return self._fail(tool_name, params, msg, session_id, "routing_blocked",
                              capability_id=decision.capability_id, origin=origin)

        manifest   = decision.manifest
        side_fx    = manifest.get("side_effects", "none") if manifest else "none"
        cap_id     = decision.capability_id

        # ── 1b. Satellite locality resolution (Fourth Pass) ───────────────────
        # For capabilities with a locality list, resolve to the best satellite.
        # Records satellite_id in evidence for provenance tracking.
        satellite_id = ""
        if self._satellite_router and manifest:
            # Model capabilities carry a locality list — resolve them.
            if manifest.get("kind") == "model":
                sat = self._satellite_router.resolve_model(cap_id, mode=mode)
                if sat:
                    satellite_id = sat.satellite_id
                    logger.debug(
                        "[tool_bus] %s → satellite %s (%s)",
                        tool_name, sat.satellite_id, sat.ollama_url,
                    )

        # ── 2. Quarantine check ───────────────────────────────────────────────
        if self._quarantine and self._quarantine.is_quarantined(cap_id):
            if mode != "repair":
                msg = (
                    f"Capability '{tool_name}' is runtime-quarantined due to repeated failures. "
                    "Switch to repair mode to attempt recovery."
                )
                logger.warning("[tool_bus] %s: quarantine block (mode=%s)", tool_name, mode)
                return self._fail(tool_name, params, msg, session_id, "quarantine_blocked",
                                  capability_id=cap_id, origin=origin)
            logger.info(
                "[tool_bus] %s: quarantined but mode=repair — allowing execution", tool_name
            )

        # ── 3. Policy ─────────────────────────────────────────────────────────
        if not self._policy.allow(action="tool_call", resource=tool_name):
            msg = f"Policy denied: cannot execute '{tool_name}'"
            logger.warning("[tool_bus] %s", msg)
            return self._fail(tool_name, params, msg, session_id, "policy_denied",
                              capability_id=cap_id, origin=origin)

        # ── 4. Execute ────────────────────────────────────────────────────────
        t0        = time.monotonic()
        error_str = ""
        try:
            raw_result = self._executor(tool_name, params)
        except Exception as e:
            raw_result = f"Tool error: {e}"
            error_str  = str(e)
            logger.error("[tool_bus] %s: %s", tool_name, e)
        duration_ms = (time.monotonic() - t0) * 1000

        # ── 5. Truncate for LLM ───────────────────────────────────────────────
        result_str = raw_result
        if len(result_str) > _MAX_RESULT_LEN:
            result_str = result_str[:_MAX_RESULT_LEN] + "\n…(truncated)"

        # ── 6. Normalize ──────────────────────────────────────────────────────
        is_error = (
            result_str.lower().startswith("unknown tool:") or
            result_str.lower().startswith("policy denied:") or
            result_str.lower().startswith("tool error:") or
            result_str.lower().startswith("error:")
        )
        normalized = NormalizedResult(
            ok=not is_error,
            summary=result_str[:200],
            data={"tool": tool_name, "params_keys": list(params.keys())},
            usable_for_claims=not is_error,
            error=error_str or (result_str if is_error else None),
        )

        # ── 7. Record ─────────────────────────────────────────────────────────
        status        = "failure" if is_error else "success"
        input_summary = (
            f"{tool_name}({', '.join(f'{k}={repr(v)[:40]}' for k, v in params.items())})"
        )

        # Update quarantine overlay on outcome.
        if self._quarantine:
            if is_error:
                self._quarantine.record_failure(cap_id)
            else:
                self._quarantine.record_success(cap_id)

        self._evidence.record_result(
            capability_id=cap_id,
            input_summary=input_summary,
            output_summary=result_str[:300],
            status=status,
            session_id=session_id,
            side_effects=side_fx,
            usable_for_claims=normalized.usable_for_claims,
            duration_ms=duration_ms,
            error=error_str,
            satellite_id=satellite_id,
            origin=origin,
        )

        logger.info(
            "[tool_bus] %s → %s (%.0fms, side_fx=%s, mode=%s)",
            tool_name, status, duration_ms, side_fx, mode,
        )
        return result_str, normalized

    def _fail(
        self,
        tool_name:     str,
        params:        dict,
        msg:           str,
        session_id:    str,
        status:        str,
        capability_id: str = "",
        origin:        str = "unverified",
    ) -> tuple[str, NormalizedResult]:
        cap_id = capability_id or f"tool.unknown.{tool_name}"
        self._evidence.record_result(
            capability_id=cap_id,
            input_summary=f"{tool_name}({list(params.keys())})",
            output_summary=msg,
            status=status,
            session_id=session_id,
            usable_for_claims=False,
            error=msg,
            origin=origin,
        )
        norm = NormalizedResult(ok=False, summary=msg, error=msg, usable_for_claims=False)
        return msg, norm
