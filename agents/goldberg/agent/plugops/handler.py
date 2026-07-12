"""
handler.py — Handles incoming messages from PlugOps.

Receives a raw message dict, routes it through the LangGraph,
sends the response back via bridge.
"""
from __future__ import annotations

import logging
import time
import uuid

from agent.core.state import AgentState
from agent.plugops.bridge import PlugOpsBridge

logger = logging.getLogger(__name__)


class MessageHandler:
    def __init__(self, graph, bridge: PlugOpsBridge, agent_name: str, mission_context: str) -> None:
        self.graph           = graph
        self.bridge          = bridge
        self.agent_name      = agent_name
        self.mission_context = mission_context

    async def handle(self, raw_message: dict) -> None:
        # PlugOps wraps messages: {"type": "message", "message": {...}}
        inner      = raw_message.get("message", raw_message)
        content    = inner.get("content", "").strip()
        from_agent = inner.get("from_agent", raw_message.get("from_agent", "unknown"))
        session_id = inner.get("session_id", raw_message.get("session_id", str(uuid.uuid4())))

        if not content:
            logger.warning(f"[handler] Empty message from {from_agent} — ignored")
            return

        logger.info(f"[handler] Message from {from_agent}: {content[:60]}")
        start = time.time()

        try:
            state = {
                "message":         content,
                "from_agent":      from_agent,
                "session_id":      session_id,
                "memory_context":  [],
                "mission_context": self.mission_context,
                "response":        "",
                "error":           None,
            }

            result = self.graph.invoke(state)
            response = result.get("response", "").strip()

            if not response:
                response = f"I received your message but had no response to generate."

            elapsed_ms = int((time.time() - start) * 1000)
            logger.info(f"[handler] Responded in {elapsed_ms}ms")

            # Always send response to dashboard so it appears in the UI
            await self.bridge.send_response("dashboard", response)

        except Exception as e:
            logger.error(f"[handler] Error processing message: {e}")
            await self.bridge.send_response(
                from_agent,
                f"I encountered an error: {e}"
            )
