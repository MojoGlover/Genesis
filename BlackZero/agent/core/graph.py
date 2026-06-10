"""
graph.py — LangGraph ReAct state machine for Engineer0.

Graph: recall → think ⇄ tool → respond

- recall:  fetch recent context from mind_state (SQLite fallback if module down)
- think:   call model_gateway for LLM inference; log cost to ledger + obs
- tool:    policy check → execute tool; counter to obs; malformed call repair
- respond: save exchange to mind_state; health beat to obs

Engineer0-specific intelligence (beyond BlackZero base):
  - TOOL_DOCS injected into every system prompt (she always has tools)
  - ANTI_HALLUCINATION_RULES injected into every system prompt
  - Widened _requires_tool_use — catches creation/build/read tasks
  - _detect_fabrication — catches false completion claims
  - Malformed tool call detection and repair loop
  - Grounding enforcement (forces tool use before answering action tasks)
  - force_rethink routing for grounding corrections
  - max_iterations configurable per-call via state
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import sqlite3

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.tools.registry import (
    TOOL_DOCS, OLLAMA_TOOL_DEFS, build_executor,
    parse_tool_call, parse_native_tool_call,
)
from agent.core.router          import CapabilityRouter
from agent.core.local_tool_bus  import LocalToolBus
from agent.core.quarantine      import QuarantineOverlay
from agent.core.satellite_router import SatelliteRouter

if TYPE_CHECKING:
    from agent.modules import Modules

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS  = 6   # hard cap for action tasks (_requires_tool_use = True)
MAX_CHAT_TOOL_ITER   = 2   # cap for spontaneous tool use on conversational messages

# Hard ceiling on a single LLM call made from the think node. Bounded well
# under /api/chat's CHAT_TIMEOUT (180s) so that even if asyncio.wait_for()
# times out the HTTP response while a call is in flight, the executor thread
# is guaranteed to come back within this many seconds — at which point the
# deadline check below ends the loop instead of starting another call.
GATEWAY_CALL_TIMEOUT = 60.0

# Injected into every system prompt — makes fabrication structurally prohibited
ANTI_HALLUCINATION_RULES = """
ABSOLUTE RULES — NEVER VIOLATE:
1. You CANNOT describe doing things you have not done. Every action claim
   (wrote a file, ran a command, restarted a service) MUST correspond to a
   [Tool result] entry in the conversation above. If there is no [Tool result]
   for it, it did not happen.
2. When a task requires system interaction, output ONLY a tool call JSON block.
   No prose before or after. No description of what you are about to do.
3. You CANNOT fabricate tool output. Never write what a tool "would" return.
   Only real [Tool result] entries count as evidence.
4. If you have completed all required steps and have [Tool result] evidence,
   you may write a plain-text summary. That summary must only reference things
   that appear in [Tool result] entries.

METICULOUS EXECUTION STANDARDS:
5. Read before you write. Never assume file contents — use read_file first.
6. Verify after every write. After writing a file, read it back to confirm it exists and contains what you wrote.
7. Check exit codes. A shell command is only successful if returncode is 0. Non-zero = failure, try again or report FAILED.
8. Never skip steps. If a task has multiple parts, complete every part. Do not summarize unfinished work as done.
9. If output is garbled, truncated, or unclear — stop and report what you actually received. Do not guess.
10. Your output must be clean, grammatically correct English. No random characters, no half-sentences, no trailing noise.
11. Never state a file path, IP address, port number, or URL you have not confirmed with a tool.
    If asked and uncertain: say "I don't know — let me check" and use list_dir or search_files.
    A wrong path delivered confidently is worse than saying you don't know.
"""


# ── Grounding helpers ──────────────────────────────────────────────────────────

def _looks_like_tool_attempt(text: str) -> bool:
    """Detect malformed tool-call attempts that should be repaired, not finalized."""
    lowered = text.lower()
    if '"tool"' in lowered or "'tool'" in lowered:
        return True
    if '"params"' in lowered or "'params'" in lowered:
        return True
    if "```json" in lowered and "tool" in lowered:
        return True
    # OpenAI/Ollama native format: {"name": "...", "arguments": {...}}
    if '"name"' in lowered and '"arguments"' in lowered:
        return True
    return False


def _requires_tool_use(message: str) -> bool:
    """
    True when the task cannot be completed without real system interaction.

    Triggers for:
    - Numbered step lists (multi-step task instructions)
    - Explicit mutation verbs (patch, write, restart, deploy, install…)
    - Creation tasks (build/create/make + artifact noun)
    - Diagnostic tasks (debug, diagnose, broken, failing…)
    - Explicit file paths in the message
    - Read/check/verify requests on system state
    """
    lowered = message.lower()

    # Todo-loop tasks always require tools — the loop prefixes them with this marker.
    if lowered.startswith("execute this task now"):
        return True

    # Numbered step lists — multi-step task instructions
    question_frame = any(kw in lowered for kw in (
        "which option", "which do you", "which would you", "which approach",
        "choose one", "explain why", "give a reason", "give your reasoning",
        "you have these options", "you have the following options",
    ))
    if not question_frame and re.search(r"^\s*\d+[\.\)]\s", message, re.MULTILINE):
        return True

    # Explicit mutation/execution verbs — cannot be faked
    mutation_terms = (
        "patch_file", "write_file", "patch ", "write ", "restart",
        "execute", "deploy", "install", "launchctl", "git commit",
        "git push", "git add", "apply the fix", "apply the patch",
        "run the ", "run this", "run: ", "shell: ",
        "scp ", "ssh ", "systemctl",
        # Messaging tools
        "send_to_agent", "list_agents", "send to agent",
        "speak with", "talk to ", "contact the", "message the",
        "send a message to", "ask the agent", "tell the agent",
        "reach out to",
    )
    if any(term in lowered for term in mutation_terms):
        return True

    # Creation/build tasks — need tools to actually produce the artifact
    creation_verbs = (
        "build", "create", "make ", "generate", "implement",
        "set up", "scaffold", "add the", "write a ", "write the ",
        "wire up", "hook up",
    )
    artifact_nouns = (
        "script", "file", "server", "module", "function", "class",
        "endpoint", "service", "tool", "agent", "plist", "config",
        "bridge", "handler", "test", "spec",
    )
    if any(v in lowered for v in creation_verbs) and any(a in lowered for a in artifact_nouns):
        return True

    # Read/check/verify — need actual data, not assumptions
    read_terms = (
        "check ", "verify ", "look at ", "read ", "what does ",
        "what is in ", "show me ", "list ", "find ",
    )
    if any(term in lowered for term in read_terms):
        if re.search(r"/[A-Za-z0-9_\-\.]+/[A-Za-z0-9_\-\./]+", message):
            return True

    # Diagnostic terms — always require tools (specific technical failures)
    diagnostic_terms_always = (
        "diagnose", "debug", "broken", "failure", "failing",
        "unable to connect", "can't connect", "cannot connect",
    )
    if any(term in lowered for term in diagnostic_terms_always):
        return True
    # Vague diagnostic questions only require tools when a path/service is mentioned —
    # avoids triggering on conversational messages like "why is my phone slow?"
    diagnostic_terms_with_path = ("why is", "what's wrong", "whats wrong")
    if any(term in lowered for term in diagnostic_terms_with_path):
        if re.search(r"/[A-Za-z0-9_\-\.]+/[A-Za-z0-9_\-\./]+", message):
            return True

    # Explicit file path in message — any path reference requires real I/O
    if re.search(r"/[A-Za-z0-9_\-\.]+/[A-Za-z0-9_\-\./]+", message):
        return True

    return False


def _any_tool_attempted(tool_history: list[dict]) -> bool:
    """True if at least one real tool execution result exists (even a failed one).
    Breaks the tool-use enforcement loop when tools were tried but all failed."""
    repair_prefixes = (
        "Tool call could not be parsed.",
        "Malformed tool call.",
        "STOP. You have not called any tools yet",
        "FABRICATION DETECTED.",
    )
    for entry in tool_history:
        if entry.get("role") != "tool_result":
            continue
        content = entry.get("content", "")
        if any(content.startswith(prefix) for prefix in repair_prefixes):
            continue
        return True
    return False


def _has_grounding_result(tool_history: list[dict]) -> bool:
    """
    True only after a real, successful tool result.
    Excludes: parser repair hints, fabrication corrections, and tool errors.
    A "Tool error: file not found" does NOT count as grounding — the model
    still hasn't verified anything real.
    """
    repair_prefixes = (
        "Tool call could not be parsed.",
        "Malformed tool call.",
        "STOP. You have not called any tools yet",
        "FABRICATION DETECTED.",
    )
    error_prefixes = (
        "Tool error:",
        "Policy denied:",
        "Unknown tool:",
        "Error:",
        "error:",
    )
    for entry in tool_history:
        if entry.get("role") != "tool_result":
            continue
        content = entry.get("content", "")
        if any(content.startswith(prefix) for prefix in repair_prefixes):
            continue
        if any(content.startswith(prefix) for prefix in error_prefixes):
            continue
        return True
    return False


def _tools_called(tool_history: list[dict]) -> set[str]:
    """Return the set of tool names that ran AND succeeded in this session.
    Pairs each assistant entry with the following tool_result; excludes failures."""
    error_prefixes = ("error:", "unknown tool:", "policy denied:", "tool error:")
    called = set()
    entries = tool_history
    for i, entry in enumerate(entries):
        if entry.get("role") != "assistant":
            continue
        tc = parse_tool_call(entry.get("content", ""))
        if not tc:
            continue
        result_entry = None
        for j in range(i + 1, len(entries)):
            if entries[j].get("role") == "tool_result":
                result_entry = entries[j]
                break
        if result_entry is None:
            continue
        result_content = result_entry.get("content", "").lower()
        if any(result_content.startswith(p) for p in error_prefixes):
            continue
        called.add(tc.get("tool", ""))
    return called


def _detect_fabrication(response: str, tool_history: list[dict]) -> str | None:
    """
    Returns a correction string if the response appears to fabricate tool results,
    or None if the response looks legitimate.

    Conservative — only flags clear-cut cases where the model claims a specific
    action without any corresponding tool call in history.
    """
    lowered = response.lower()
    called  = _tools_called(tool_history)
    write_tools = {"write_file", "patch_file", "shell", "python"}
    run_tools   = {"shell", "python"}

    # Claimed file was written but no write/shell/python tool was ever called
    write_claim_patterns = (
        "i've written", "i have written", "i created the file",
        "file has been written", "file has been created", "i wrote the",
        "successfully written", "have been saved", "has been saved",
        "written to disk", "i completed the task", "task complete",
        "task is complete", "i have completed", "i've completed",
        "all done", "the work is done", "here is the result",
        "here are the results", "the file is ready", "the script is ready",
        "the report is ready", "done:", "finished:",
        "i've updated", "i have updated", "i updated the",
        "changes applied", "changes have been applied", "config modified",
        "configuration updated", "i modified", "i've modified",
        "has been updated", "has been modified", "has been applied",
        "successfully updated", "successfully modified", "successfully applied",
    )
    if any(p in lowered for p in write_claim_patterns):
        if not called.intersection(write_tools):
            return (
                "FABRICATION DETECTED. You claimed the task is done or a file exists, but no "
                "write_file, patch_file, shell, or python tool was called. "
                "Nothing has actually been written or executed. "
                "You MUST call the appropriate tool now. Output a tool call JSON block."
            )

    # Claimed command was run but no shell/python tool was called
    # read_file and write_file also ground "the result is / the output is" —
    # those phrases appear naturally after file reads, not just shell commands.
    run_claim_patterns = (
        "i ran ", "i executed ", "i ran the", "command ran",
        "command executed", "successfully ran", "i restarted",
        "i deployed", "i installed", "i started ", "i stopped ",
        "the test passed", "tests pass", "test runs",
        "it works", "it's working", "it is working",
    )
    run_grounding = run_tools | {"read_file", "write_file", "list_dir"}
    if any(p in lowered for p in run_claim_patterns):
        if not called.intersection(run_grounding):
            return (
                "FABRICATION DETECTED. You claimed a command ran or produced output, but no "
                "shell or python tool was called. "
                "You MUST call the shell tool to actually execute commands. "
                "Output a tool call JSON block now."
            )

    # Claimed to have read a file but no read_file tool was called
    read_claim_patterns = (
        "i read the file", "i checked the file", "looking at the file",
        "the file contains", "the file shows", "the contents of",
        "i reviewed", "i examined", "i analyzed the",
    )
    if any(p in lowered for p in read_claim_patterns):
        if "read_file" not in called and "shell" not in called:
            return (
                "FABRICATION DETECTED. You claimed to have read a file, but no "
                "read_file or shell tool was called. "
                "You MUST call read_file to actually read a file. "
                "Output a tool call JSON block now."
            )

    return None


# ── Node factories ─────────────────────────────────────────────────────────────

def make_recall_node(mods: "Modules"):
    def recall(state: dict) -> dict:
        session_id = state.get("session_id", "default")
        message    = state.get("message", "")
        if data_dir := state.get("data_dir", state.get("_data_dir", "")):
            mods.mind_state.set_fallback_dir(Path(data_dir))

        # Recent turns (recency-based context)
        recent = mods.mind_state.get_recent(session_id, limit=4)

        # Semantic memory — find relevant past exchanges beyond the last 4 turns.
        # Skip for short messages — not worth the overhead for simple greetings.
        semantic = mods.rag.search(message, k=3) if len(message) > 80 else []

        # Merge: recent first, then semantic hits not already in recent
        recent_set = set(recent)
        merged = recent + [s for s in semantic if s not in recent_set]

        # Always reset max_iterations so stale checkpoints don't carry an old value.
        # tool_required caps spontaneous tool loops to MAX_CHAT_TOOL_ITER.
        return {
            **state,
            "memory_context":    merged,
            "tool_history":      [],
            "tool_iterations":   0,
            "max_iterations":    MAX_TOOL_ITERATIONS,
            "tool_required":     _requires_tool_use(message),
            "tool_call_pending": False,
            "force_rethink":     False,
            "tools_ran":        0,
            "_tools_ran":       0,
            "last_result":      {},
            "_last_result":     {},
        }
    return recall


def make_think_node(mods: "Modules", system_prompt: str):
    def think(state: dict) -> dict:
        message      = state.get("message", "")
        memory       = state.get("memory_context", [])
        tool_history = state.get("tool_history", [])
        iterations    = state.get("tool_iterations", 0)
        tool_required = state.get("tool_required", False)
        max_iter      = state.get("max_iterations", MAX_TOOL_ITERATIONS)
        # Spontaneous tool use on conversational messages: cap at MAX_CHAT_TOOL_ITER.
        if not tool_required:
            max_iter = min(max_iter, MAX_CHAT_TOOL_ITER)

        if iterations >= max_iter:
            logger.warning(f"[think] max iterations ({max_iter}) reached")
            # FAILED: prefix so task loops route to mark_failed, not mark_done.
            summary = "FAILED: max iterations reached without completing the task. Partial work:\n"
            for entry in tool_history:
                if entry["role"] == "tool_result":
                    summary += f"\n- {entry['content'][:1000]}"
            return {**state, "response": summary, "tool_call_pending": False}

        # ── Cooperative deadline check ──────────────────────────────────────────
        # /api/chat sets `_deadline` (a time.monotonic() cutoff) before invoking
        # the graph. asyncio.wait_for() can only abandon the HTTP response when
        # CHAT_TIMEOUT elapses — it cannot kill the executor thread running this
        # code. Without this check, a thread that's between iterations when the
        # HTTP timeout fires would go on to start ANOTHER LLM call (up to
        # GATEWAY_CALL_TIMEOUT seconds) for no one. Checking here, before issuing
        # the next LLM call, lets an already-timed-out request exit on its own
        # within one iteration instead of running indefinitely in the background.
        deadline = state.get("_deadline")
        if deadline is not None and time.monotonic() >= deadline:
            logger.warning("[think] Deadline already exceeded — aborting without further LLM calls")
            return {**state,
                    "response":          "FAILED: deadline exceeded before this iteration started.",
                    "tool_call_pending": False,
                    "force_rethink":     False}

        # Pick model tier early — needed to decide whether TOOL_DOCS is included.
        if iterations > 0 or tool_history:
            task_type = "fast"
        elif _requires_tool_use(message):
            task_type = "reasoning"
        else:
            task_type = "chat"

        use_native_tools = (task_type in ("reasoning", "fast", "code"))

        # Include TOOL_DOCS and ANTI_HALLUCINATION_RULES only when tools are in play.
        # For plain chat, injecting anti-hallucination rules causes the model to
        # attempt tool calls for conversational messages (rule 2: "output ONLY a
        # tool call JSON block"), which escalates greetings into the heavy inference
        # path and runs shell commands on "hey".
        if use_native_tools or tool_history:
            system = f"{system_prompt}\n\n{ANTI_HALLUCINATION_RULES}\n\n{TOOL_DOCS}"
        elif task_type == "chat":
            system = system_prompt
        else:
            system = f"{system_prompt}\n\n{ANTI_HALLUCINATION_RULES}"

        # Cap tool history before building messages — prevents context explosion on long tasks.
        _MAX_TOOL_HISTORY = 30
        if len(tool_history) > _MAX_TOOL_HISTORY:
            tool_history = tool_history[-_MAX_TOOL_HISTORY:]

        if tool_history:
            parts = []
            if memory and iterations == 0:
                parts.append("Previous conversation:\n" + "\n".join(memory))
            parts.append(f"Task: {message}")
            for e in tool_history:
                if e["role"] == "assistant":
                    parts.append(f"[You called a tool]: {e['content']}")
                elif e["role"] == "tool_result":
                    parts.append(f"[Tool result]: {e['content']}")
            human_content = "\n\n".join(parts)
        else:
            parts = []
            if memory:
                parts.append("Previous conversation:\n" + "\n".join(memory))
            # "Task:" prefix primes the model for execution. Plain message for chat.
            parts.append(message if task_type == "chat" else f"Task: {message}")
            human_content = "\n\n".join(parts)

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": human_content},
        ]

        # tool definitions payload — already determined above with task_type
        tools_payload = OLLAMA_TOOL_DEFS if use_native_tools else None

        logger.debug(f"[think] LLM call #{iterations + 1} task_type={task_type} native_tools={use_native_tools}")
        try:
            result = mods.gateway.chat_for(messages, task_type=task_type,
                                           tools=tools_payload,
                                           timeout=GATEWAY_CALL_TIMEOUT)
        except Exception as e:
            logger.error(f"[think] gateway error: {e}")
            return {**state, "response": f"LLM error: {e}", "tool_call_pending": False}

        response_text = result.get("content", "").strip()

        # Cost + observability
        mods.ledger.record_llm(
            model_id      = result.get("model_id", "unknown"),
            input_tokens  = result.get("input_tokens", 0),
            output_tokens = result.get("output_tokens", 0),
            cost_usd      = result.get("cost_usd", 0.0),
        )
        mods.obs.histogram("llm_latency_ms", result.get("latency_ms", 0))

        # Check native tool_calls first (Ollama enforced format — no parsing needed),
        # then fall back to text-based parse_tool_call for non-native responses.
        tool_call = parse_native_tool_call(result) or parse_tool_call(response_text)
        if tool_call:
            import json as _json
            # Suppress spontaneous tool calls on conversational messages.
            # Tool-trained models emit tool call JSON even without being offered tools.
            # Re-prompt once rather than executing to prevent unintended side effects.
            if not tool_required:
                logger.info(f"[think] Suppressing tool call '{tool_call['tool']}' on chat message (tool_required=False)")
                return {**state,
                        "tool_history": tool_history + [
                            {"role": "assistant",  "content": response_text},
                            {"role": "tool_result", "content":
                             "This is a conversational message. Answer directly without using any tools."},
                        ],
                        "tool_iterations":   iterations + 1,
                        "tool_call_pending": False,
                        "force_rethink":     True,
                        "last_result":       {},
                        "_last_result":      {}}
            logger.info(f"[think] Tool call: {tool_call['tool']}({list(tool_call.get('params', {}).keys())})")
            tool_call_text = response_text or _json.dumps({"tool": tool_call["tool"], "params": tool_call.get("params", {})})
            return {**state,
                    "tool_history":     tool_history + [{"role": "assistant", "content": tool_call_text}],
                    "tool_iterations":  iterations + 1,
                    "tool_call_pending": True,
                    "force_rethink":    False,
                    "last_result":     result,
                    "_last_result":    result,
                    "response":         tool_call_text}

        # ── Fabrication detection — catches false completion claims ────────────
        fabrication_msg = _detect_fabrication(response_text, tool_history)
        if fabrication_msg:
            logger.warning("[think] Fabrication detected — injecting correction")
            if iterations + 1 >= max_iter:
                return {**state,
                        "response":          f"FAILED: fabricated completion detected on final iteration. {response_text[:200]}",
                        "tool_call_pending": False,
                        "force_rethink":     False}
            return {**state,
                    "tool_history": tool_history + [
                        {"role": "assistant",  "content": response_text},
                        {"role": "tool_result", "content": fabrication_msg},
                    ],
                    "tool_iterations":   iterations + 1,
                    "tool_call_pending": False,
                    "force_rethink":     True,
                    "last_result":      {},
                    "_last_result":     {},
                    "response":          ""}

        # ── Malformed tool call — send back for repair ─────────────────────────
        if _looks_like_tool_attempt(response_text):
            logger.warning("[think] Malformed tool call — routing to repair")
            return {**state,
                    "tool_history":     tool_history + [{"role": "assistant", "content": response_text}],
                    "tool_iterations":  iterations + 1,
                    "tool_call_pending": True,
                    "force_rethink":    False,
                    "last_result":      {},
                    "_last_result":     {},
                    "response":         response_text}

        # Tool-use enforcement — any action or diagnostic task must use tools before responding.
        # NOTE: no max_iter escape hatch here. On the final iteration, if no real tool was
        # called, we still inject the correction. The model will hit max_iter on the NEXT
        # pass and get the iteration-limit summary — which is better than a hallucinated
        # "completion" slipping through on the last allowed iteration.
        if (_requires_tool_use(message) and
                not _has_grounding_result(tool_history) and
                not _any_tool_attempted(tool_history)):
            logger.warning("[think] Action task answered without any tool calls — forcing tool use")
            # Extract the first concrete action from the message to guide the next call
            first_action = message.strip().split("\n")[0][:120]
            correction = (
                f"STOP. You have not called any tools yet but this task requires real system actions.\n\n"
                f"Do NOT summarize or describe what you would do. You MUST output a tool call JSON block RIGHT NOW.\n\n"
                f"The task starts with: \"{first_action}\"\n\n"
                f"Output ONLY a JSON block for the first tool call needed. No prose. No explanation. Just:\n"
                f'```json\n{{"tool": "<tool_name>", "params": {{...}}}}\n```'
            )
            return {**state,
                    "tool_history": tool_history + [
                        {"role": "assistant",  "content": response_text},
                        {"role": "tool_result", "content": correction},
                    ],
                    "tool_iterations":  iterations + 1,
                    "tool_call_pending": False,
                    "force_rethink":    True,
                    "response":         ""}

        # Plain text — done; clear last_result so stale native tool calls don't replay
        return {**state,
                "response":         response_text,
                "tool_call_pending": False,
                "tool_iterations":  iterations,
                "force_rethink":    False,
                "last_result":      {},
                "_last_result":     {}}

    return think


def make_tool_node(local_tool_bus: "LocalToolBus", mods: "Modules"):
    def tool(state: dict) -> dict:
        # Try native tool_calls format first (from gateway result stored in state),
        # then fall back to text parsing from the response string.
        tool_call = parse_native_tool_call(state.get("last_result", state.get("_last_result", {}))) \
                 or parse_tool_call(state.get("response", ""))
        if not tool_call:
            logger.warning("[tool] No valid tool call — injecting repair hint")
            repair = (
                "Tool call could not be parsed. Return exactly one JSON object like "
                '{"tool": "read_file", "params": {"path": "/path/to/file"}} with no prose.'
            )
            return {**state,
                    "tool_history": state.get("tool_history", []) + [
                        {"role": "tool_result", "content": repair}
                    ],
                    "tool_call_pending": False,
                    "force_rethink":     True,
                    "last_result":      {},
                    "_last_result":     {}}

        tool_name  = tool_call.get("tool", "")
        params     = tool_call.get("params", {})
        session_id = state.get("session_id", "")

        # Route → quarantine → policy → execute → normalize → record evidence (all in bus)
        mode = state.get("mode", "act")
        result_str, normalized = local_tool_bus.execute(
            tool_name, params, session_id=session_id, mode=mode
        )

        mods.obs.counter("tool_calls_total", labels={"tool": tool_name})

        # Only count real executions toward tools_ran — failed/denied calls
        # go into tool_history so the model sees the failure, but are not
        # treated as evidence that real work was done.
        real_execution = normalized.usable_for_claims
        new_tools_ran = state.get("tools_ran", state.get("_tools_ran", 0)) + (1 if real_execution else 0)

        return {**state,
                "tool_history": state.get("tool_history", []) + [
                    {"role": "tool_result", "content": result_str}
                ],
                "tools_ran":        new_tools_ran,
                "_tools_ran":       new_tools_ran,
                "last_result":      {},   # clear so stale native tool_calls can't replay
                "_last_result":     {},
                "tool_call_pending": False}

    return tool


_SPEECH_SYSTEM = (
    "You are a delivery layer. The agent has finished reasoning. "
    "Your job: take the agent's output and deliver it to the user clearly, "
    "concisely, and conversationally. Never add caveats, apologies, or meta-commentary. "
    "If the output is already short and clean, return it unchanged. "
    "Never invent information not present in the agent's output."
)

# Responses shorter than this are already clean — skip the speech pass.
_SPEECH_SKIP_CHARS = 280


def make_respond_node(mods: "Modules"):
    def respond(state: dict) -> dict:
        session_id = state.get("session_id", "default")
        message    = state.get("message", "")
        response   = state.get("response", "")

        # ── Speech brain: fast delivery pass ──────────────────────────────────
        # Only runs when:
        #   - a speech model is configured (models.speech in config)
        #   - the inference response is long enough to need polishing
        #   - the response isn't already just a tool result (from_agent != "user" skips)
        speech_model = mods.gateway._model_for("speech")
        from_agent   = state.get("from_agent", "user")
        if (speech_model
                and speech_model != mods.gateway._model_for("chat")  # only if different model
                and from_agent == "user"                              # skip agent-to-agent
                and len(response) > _SPEECH_SKIP_CHARS):             # skip short responses
            try:
                result = mods.gateway.chat_for(
                    messages=[
                        {"role": "system",    "content": _SPEECH_SYSTEM},
                        {"role": "user",      "content": f"User asked: {message}\n\nAgent output:\n{response}"},
                    ],
                    task_type="speech",
                    max_tokens=1024,
                    timeout=30.0,
                )
                polished = result.get("content", "").strip()
                if polished:
                    response = polished
                    mods.ledger.record_llm(
                        model_id      = result.get("model_id", "speech"),
                        input_tokens  = result.get("input_tokens", 0),
                        output_tokens = result.get("output_tokens", 0),
                        cost_usd      = result.get("cost_usd", 0.0),
                    )
                    logger.debug(f"[respond] speech pass complete ({len(polished)} chars)")
            except Exception as e:
                logger.warning(f"[respond] speech pass failed: {e!r} — using raw response")

        mods.mind_state.save(session_id, message, response)
        mods.rag.index(session_id, message, response)
        mods.obs.beat(status="ok")
        # NOTE: tool_history and _tools_ran are intentionally preserved in the
        # returned state so that callers (todo_loop, task_loop) can verify that
        # real tool execution happened before marking a task complete.
        return {**state,
                "response":          response,
                "tool_iterations":   0,
                "tool_call_pending": False,
                "force_rethink":     False}
    return respond


def should_continue(state: dict) -> str:
    if state.get("tool_call_pending"):
        return "tool"
    if state.get("force_rethink"):
        return "think"
    return "respond"


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_graph(config: dict, system_prompt: str, data_dir: Path, mods: "Modules"):
    """Build and compile the Engineer0 ReAct graph."""
    execute_tool     = build_executor()
    registry_dir     = Path(__file__).resolve().parent.parent.parent / "registry"
    router           = CapabilityRouter(registry_dir)
    satellite_router = SatelliteRouter(registry_dir)
    quarantine       = QuarantineOverlay(data_dir)
    tool_bus         = LocalToolBus(
        execute_tool, router, mods.policy, mods.evidence, quarantine, satellite_router
    )

    graph = StateGraph(dict)
    graph.add_node("recall",  make_recall_node(mods))
    graph.add_node("think",   make_think_node(mods, system_prompt))
    graph.add_node("tool",    make_tool_node(tool_bus, mods))
    graph.add_node("respond", make_respond_node(mods))

    graph.set_entry_point("recall")
    graph.add_edge("recall", "think")
    graph.add_conditional_edges("think", should_continue,
                                {"tool": "tool", "think": "think", "respond": "respond"})
    graph.add_edge("tool", "think")
    graph.add_edge("respond", END)

    # Persistent checkpointing — survives crashes, enables mid-task resume.
    # WAL mode keeps writes non-blocking while reads continue.
    checkpoint_path = data_dir / "checkpoints.db"
    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    checkpointer = SqliteSaver(conn)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info(f"[graph] Compiled with checkpointer → {checkpoint_path}")
    return compiled
