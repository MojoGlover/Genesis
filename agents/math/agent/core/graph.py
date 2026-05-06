"""
graph.py — LangGraph ReAct state machine.

Graph: recall → think ⇄ tool → respond

- recall:  fetch recent context from mind_state (local SQLite fallback if module down)
- think:   call model_gateway for LLM inference; log cost to ledger + obs
- tool:    policy check → execute tool; counter to obs
- respond: save exchange to mind_state; health beat to obs

Tool call format (LLM must output this — and ONLY this in that turn):
    ```json
    {"tool": "<name>", "params": {…}}
    ```
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, END

from agent.tools.registry import build_executor, parse_tool_call

if TYPE_CHECKING:
    from agent.modules import Modules

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 20


# ── Node factories ─────────────────────────────────────────────────────────────

def make_recall_node(mods: "Modules"):
    def recall(state: dict) -> dict:
        session_id = state.get("session_id", "default")
        if data_dir := state.get("_data_dir"):
            mods.mind_state.set_fallback_dir(Path(data_dir))
        memory = mods.mind_state.get_recent(session_id, limit=6)
        return {**state, "memory_context": memory}
    return recall


def make_think_node(mods: "Modules", system_prompt: str):
    def think(state: dict) -> dict:
        message      = state.get("message", "")
        memory       = state.get("memory_context", [])
        tool_history = state.get("tool_history", [])
        iterations   = state.get("tool_iterations", 0)

        if iterations >= MAX_TOOL_ITERATIONS:
            logger.warning(f"[think] max iterations ({MAX_TOOL_ITERATIONS}) reached")
            return {**state,
                    "response": "Reached tool call limit. Summary: " + state.get("response", ""),
                    "tool_call_pending": False}

        # Build messages for LLM
        if tool_history:
            parts = []
            if memory:
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
            parts.append(f"Task: {message}")
            human_content = "\n\n".join(parts)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": human_content},
        ]

        logger.debug(f"[think] LLM call #{iterations + 1}")
        try:
            result = mods.gateway.chat(messages, capability="chat")
        except Exception as e:
            logger.error(f"[think] gateway error: {e}")
            return {**state, "response": f"LLM error: {e}", "tool_call_pending": False}

        response_text = result.get("content", "").strip()

        # Cost tracking
        mods.ledger.record_llm(
            model_id      = result.get("model_id", "unknown"),
            input_tokens  = result.get("input_tokens", 0),
            output_tokens = result.get("output_tokens", 0),
            cost_usd      = result.get("cost_usd", 0.0),
        )
        mods.obs.histogram("llm_latency_ms", result.get("latency_ms", 0))

        tool_call = parse_tool_call(response_text)
        if tool_call:
            logger.info(f"[think] Tool call: {tool_call['tool']}")
            return {**state,
                    "tool_history": tool_history + [{"role": "assistant", "content": response_text}],
                    "tool_iterations": iterations + 1,
                    "tool_call_pending": True,
                    "response": response_text}

        return {**state, "response": response_text,
                "tool_call_pending": False,
                "tool_iterations": iterations + 1}

    return think


def make_tool_node(execute_tool, mods: "Modules"):
    def tool(state: dict) -> dict:
        tool_call = parse_tool_call(state.get("response", ""))
        if not tool_call:
            logger.warning("[tool] No valid tool call found")
            return {**state, "tool_call_pending": False}

        tool_name = tool_call.get("tool", "")
        params    = tool_call.get("params", {})

        if not mods.policy.allow(action="tool_call", resource=tool_name):
            logger.warning(f"[tool] Policy denied: {tool_name}")
            result_str = f"Policy denied: cannot execute '{tool_name}'"
        else:
            logger.info(f"[tool] Executing: {tool_name}")
            try:
                result_str = execute_tool(tool_name, params)
            except Exception as e:
                result_str = f"Tool error: {e}"
                logger.error(f"[tool] {tool_name}: {e}")

        if len(result_str) > 8000:
            result_str = result_str[:8000] + "\n…(truncated)"

        mods.obs.counter("tool_calls_total", labels={"tool": tool_name})

        return {**state,
                "tool_history": state.get("tool_history", []) + [
                    {"role": "tool_result", "content": result_str}
                ],
                "tool_call_pending": False}

    return tool


def make_respond_node(mods: "Modules"):
    def respond(state: dict) -> dict:
        mods.mind_state.save(
            state.get("session_id", "default"),
            state.get("message", ""),
            state.get("response", ""),
        )
        mods.obs.beat(status="ok")
        return {**state, "tool_history": [], "tool_iterations": 0, "tool_call_pending": False}
    return respond


def should_continue(state: dict) -> str:
    return "tool" if state.get("tool_call_pending") else "respond"


# ── Graph builder ──────────────────────────────────────────────────────────────

def build_graph(config: dict, system_prompt: str, data_dir: Path, mods: "Modules"):
    """Build and compile the ReAct graph."""
    execute_tool = build_executor()

    graph = StateGraph(dict)
    graph.add_node("recall",  make_recall_node(mods))
    graph.add_node("think",   make_think_node(mods, system_prompt))
    graph.add_node("tool",    make_tool_node(execute_tool, mods))
    graph.add_node("respond", make_respond_node(mods))

    graph.set_entry_point("recall")
    graph.add_edge("recall", "think")
    graph.add_conditional_edges("think", should_continue,
                                {"tool": "tool", "respond": "respond"})
    graph.add_edge("tool", "think")
    graph.add_edge("respond", END)

    compiled = graph.compile()
    logger.info("[graph] Compiled: recall → think ⇄ tool → respond")
    return compiled
