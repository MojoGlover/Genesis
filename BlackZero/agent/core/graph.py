"""
graph.py — LangGraph ReAct state machine for Engineer0.

Graph: recall -> think -> tool (loop) -> respond

The think node calls the LLM. If it outputs a tool call JSON block,
the tool node executes it and feeds the result back to think.
This loops until the LLM produces a plain-text response (no tool call),
or until max_iterations is hit.

Tool call format (LLM must output this):
    ```json
    {"tool": "shell", "params": {"command": "ls"}}
    ```
"""
from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END

from agent.core.state import AgentState
from agent.tools.registry import TOOL_DOCS, build_executor, parse_tool_call

logger = logging.getLogger(__name__)

# ── Database ──────────────────────────────────────────────────────────────────

def _get_db(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(data_dir / "memory.db"))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            ts         TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _fetch_recent(data_dir: Path, session_id: str, limit: int = 6) -> list[str]:
    try:
        conn = _get_db(data_dir)
        rows = conn.execute(
            "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        conn.close()
        return [f"{role}: {content}" for role, content in reversed(rows)]
    except Exception as e:
        logger.warning(f"[memory] fetch failed: {e}")
        return []


def _save_exchange(data_dir: Path, session_id: str, human: str, assistant: str) -> None:
    try:
        conn = _get_db(data_dir)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (session_id, "human", human, ts),
        )
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (session_id, "assistant", assistant, ts),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[memory] save failed: {e}")


# ── Nodes ─────────────────────────────────────────────────────────────────────

def make_recall_node(data_dir: Path):
    def recall(state: dict) -> dict:
        session_id = state.get("session_id") or str(uuid.uuid4())
        recent = _fetch_recent(data_dir, session_id)
        logger.debug(f"[recall] {len(recent)} memory entries")
        return {
            **state,
            "session_id": session_id,
            "memory_context": recent,
            "tool_history": [],
            "tool_iterations": 0,
            "tool_call_pending": False,
        }
    return recall


def make_think_node(llm: ChatOllama, mission_context: str):
    def think(state: dict) -> dict:
        iterations = state.get("tool_iterations", 0)
        max_iter = state.get("max_iterations", 10)
        tool_history = state.get("tool_history", [])
        memory = state.get("memory_context", [])
        message = state.get("message", "")

        # Guard against runaway loops
        if iterations >= max_iter:
            logger.warning(f"[think] Max iterations ({max_iter}) reached")
            summary = "I reached the maximum number of tool calls. Here's what I accomplished:\n"
            for entry in tool_history:
                if entry["role"] == "tool_result":
                    summary += f"\n- {entry['content'][:200]}"
            return {**state, "response": summary, "tool_call_pending": False}

        # Build message history for LLM
        # System prompt = mission + tool docs
        system = f"{mission_context}\n\n{TOOL_DOCS}"

        # Human turn = memory context + current message
        if tool_history:
            # We're mid-ReAct loop — pass accumulated history
            human_parts = []
            if memory and iterations == 0:
                human_parts.append("Previous conversation:\n" + "\n".join(memory))
            human_parts.append(f"Task: {message}")
            for entry in tool_history:
                role = entry["role"]
                content = entry["content"]
                if role == "assistant":
                    human_parts.append(f"[You called a tool]: {content}")
                elif role == "tool_result":
                    human_parts.append(f"[Tool result]: {content}")
            human_content = "\n\n".join(human_parts)
        else:
            # First turn
            human_parts = []
            if memory:
                human_parts.append("Previous conversation:\n" + "\n".join(memory))
            human_parts.append(f"Task: {message}")
            human_content = "\n\n".join(human_parts)

        messages = [
            SystemMessage(content=system),
            HumanMessage(content=human_content),
        ]

        logger.debug(f"[think] LLM call #{iterations + 1}")
        try:
            result = llm.invoke(messages)
            response_text = result.content.strip()
        except Exception as e:
            logger.error(f"[think] LLM call failed: {e}")
            return {**state, "response": f"LLM error: {e}", "tool_call_pending": False}

        # Check if LLM wants to call a tool
        tool_call = parse_tool_call(response_text)
        if tool_call:
            logger.info(f"[think] Tool call: {tool_call['tool']}({list(tool_call.get('params', {}).keys())})")
            new_history = tool_history + [{"role": "assistant", "content": response_text}]
            return {
                **state,
                "tool_history": new_history,
                "tool_iterations": iterations + 1,
                "tool_call_pending": True,
                "response": response_text,  # holds the tool call JSON
            }
        else:
            # Plain text response — we're done
            return {
                **state,
                "response": response_text,
                "tool_call_pending": False,
                "tool_iterations": iterations + 1,
            }

    return think


def make_tool_node(execute_tool):
    def tool(state: dict) -> dict:
        response = state.get("response", "")
        tool_history = state.get("tool_history", [])

        tool_call = parse_tool_call(response)
        if not tool_call:
            logger.warning("[tool] No valid tool call found in response")
            return {**state, "tool_call_pending": False}

        tool_name = tool_call.get("tool", "")
        params = tool_call.get("params", {})

        logger.info(f"[tool] Executing: {tool_name}")
        try:
            result_str = execute_tool(tool_name, params)
        except Exception as e:
            result_str = f"Tool execution error: {e}"
            logger.error(f"[tool] {e}")

        # Truncate very long results
        if len(result_str) > 8000:
            result_str = result_str[:8000] + "\n... (truncated)"

        logger.debug(f"[tool] Result ({len(result_str)} chars)")

        new_history = tool_history + [{"role": "tool_result", "content": result_str}]
        return {
            **state,
            "tool_history": new_history,
            "tool_call_pending": False,
        }

    return tool


def make_respond_node(data_dir: Path):
    def respond(state: dict) -> dict:
        _save_exchange(
            data_dir,
            state.get("session_id", "default"),
            state.get("message", ""),
            state.get("response", ""),
        )
        logger.debug(f"[respond] Exchange saved — {state.get('tool_iterations', 0)} tool call(s)")
        return {
            **state,
            "tool_history": [],
            "tool_iterations": 0,
            "tool_call_pending": False,
        }
    return respond


# ── Routing ───────────────────────────────────────────────────────────────────

def should_continue(state: dict) -> str:
    """Route: if tool call pending → tool → think loop. Otherwise → respond."""
    if state.get("tool_call_pending"):
        return "tool"
    return "respond"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph(config: dict, mission_context: str, data_dir: Path):
    """
    Build and compile the Engineer0 ReAct graph.
    Returns (compiled_graph, llm).
    """
    model_name = config.get("models", {}).get("chat", "engineer0:latest")
    ollama_url = config.get("tools", {}).get("ollama_api", "http://localhost:11434")
    base_url = ollama_url.rstrip("/api").rstrip("/")

    llm = ChatOllama(model=model_name, base_url=base_url)
    logger.info(f"[graph] LLM: {model_name} via {base_url}")

    execute_tool = build_executor()

    recall  = make_recall_node(data_dir)
    think   = make_think_node(llm, mission_context)
    tool    = make_tool_node(execute_tool)
    respond = make_respond_node(data_dir)

    graph = StateGraph(dict)
    graph.add_node("recall", recall)
    graph.add_node("think", think)
    graph.add_node("tool", tool)
    graph.add_node("respond", respond)

    graph.set_entry_point("recall")
    graph.add_edge("recall", "think")
    graph.add_conditional_edges("think", should_continue, {"tool": "tool", "respond": "respond"})
    graph.add_edge("tool", "think")  # tool result feeds back to think
    graph.add_edge("respond", END)

    compiled = graph.compile()
    logger.info("[graph] ReAct graph compiled: recall → think ⇄ tool → respond")
    return compiled, llm
