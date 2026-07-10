"""
handler.py — Handles incoming messages from PlugOps.

Receives a raw message dict, routes it through the LangGraph,
sends the response back via bridge.

Fixes applied (propagate from Engineer0):
  FIX 1: HANDLER_TIMEOUT 650s (was 170) — long tool chains need room
  FIX 2: flat string inner — PlugOps chat payloads send message as a plain
          string, not a nested dict; isinstance(inner, str) handles both forms
  FIX 3: request_id on all error paths — without it PlugOps cannot resolve
          the pending future and the caller hangs until its own timeout fires
  FIX 4: removed duplicate dashboard send — PlugOps fans out to dashboard
          itself; double-sending caused duplicate bubbles in the chat view
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from agent.plugops.bridge import PlugOpsBridge

logger = logging.getLogger(__name__)

HANDLER_TIMEOUT = 650  # seconds — must be < server.py CHAT_TIMEOUT (660)


class MessageHandler:
    def __init__(
        self,
        graph,
        bridge:          PlugOpsBridge,
        agent_name:      str,
        mission_context: str,
        data_dir:        "Path | None" = None,
        mods=None,
    ) -> None:
        self.graph           = graph
        self.bridge          = bridge
        self.agent_name      = agent_name
        self.mission_context = mission_context
        self._data_dir       = data_dir or Path("~/.agent").expanduser()
        self._mods           = mods

    async def handle(self, raw_message: dict) -> None:
        # PlugOps wraps messages in two ways:
        #   nested:  {"type": "message", "message": {"content": "...", ...}}
        #   flat:    {"type": "chat", "message": "hello", "request_id": "..."}
        inner = raw_message.get("message", raw_message)
        if isinstance(inner, str):
            content    = inner.strip()
            from_agent = raw_message.get("from_agent", "unknown")
            session_id = raw_message.get("session_id", str(uuid.uuid4()))
            request_id = raw_message.get("request_id", "")
        else:
            content    = inner.get("content", "").strip()
            from_agent = inner.get("from_agent", raw_message.get("from_agent", "unknown"))
            session_id = inner.get("session_id", raw_message.get("session_id", str(uuid.uuid4())))
            request_id = inner.get("request_id", raw_message.get("request_id", ""))

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
                "data_dir":        str(self._data_dir),
            }

            loop   = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.graph.invoke(
                        state,
                        config={
                            "configurable": {"thread_id": session_id},
                            "recursion_limit": 100,
                        },
                    ),
                ),
                timeout=HANDLER_TIMEOUT,
            )
            response = result.get("response", "").strip()

            if not response:
                response = "I received your message but had no response to generate."

            elapsed_ms = int((time.time() - start) * 1000)
            logger.info(f"[handler] Responded in {elapsed_ms}ms")

            # request_id lets PlugOps resolve the pending future and return
            # the reply to the caller. PlugOps fans out to the dashboard itself.
            await self.bridge.send_response(from_agent, response, request_id=request_id)

            # Evaluator-Optimizer hardening check — scheduled AFTER the response
            # is already sent, so a slow/hung judge call can never add latency
            # to, or fail, the user-facing reply. Fire-and-forget.
            self._schedule_hardening_eval(
                message=content, from_agent=from_agent, response=response,
                tool_history=result.get("tool_history", []),
                tools_ran=result.get("tools_ran", 0),
                session_id=session_id,
            )

        except asyncio.TimeoutError:
            logger.error(
                f"[handler] Timed out after {HANDLER_TIMEOUT}s processing message from {from_agent}"
            )
            await self.bridge.send_response(
                from_agent,
                f"Request timed out after {HANDLER_TIMEOUT}s.",
                request_id=request_id,
            )
        except Exception as e:
            logger.error(f"[handler] Error processing message: {e}")
            await self.bridge.send_response(
                from_agent,
                f"I encountered an error: {e}",
                request_id=request_id,
            )

    def _schedule_hardening_eval(self, **kwargs) -> None:
        """Fire-and-forget: never awaited by the caller, never adds latency to
        the response, and any internal exception is caught here so it can't
        surface as an unhandled asyncio Task exception. HardeningEvalClient is
        sync, so it runs in an executor thread — same pattern as graph.invoke()."""
        if self._mods is None:
            return

        async def _run() -> None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: self._mods.hardening.evaluate(**kwargs))
            except Exception as e:
                logger.warning(f"[handler] hardening eval task failed: {e!r}")

        asyncio.create_task(_run())
