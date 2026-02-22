"""
ConversationRelay WebSocket server.
Twilio connects here when an inbound call uses ConversationRelay.

Start with: server = ConversationRelayServer(ai_chat_fn=my_fn); server.run()
The server listens on ws://0.0.0.0:8765 by default.

Flow: Twilio dials number → hits /twilio/voice/inbound → returns TwiML with 
      wss://yourserver:8765 → Twilio connects WebSocket here → real-time voice AI
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ConversationRelayServer:
    def __init__(
        self,
        ai_chat_fn: Optional[Callable] = None,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        self.ai_chat_fn = ai_chat_fn or self._default_handler
        self.host = host
        self.port = port

    def _default_handler(self, text: str) -> str:
        return f"Engineer Zero received: {text}"

    async def _handle_connection(self, websocket):
        """Handle a single ConversationRelay WebSocket session."""
        from .voice import VoiceBridge
        bridge = VoiceBridge()
        logger.info(f"ConversationRelay connected: {websocket.remote_address}")

        try:
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                    response = bridge.handle_conversation_relay_message(
                        msg, self.ai_chat_fn
                    )
                    if response:
                        await websocket.send(json.dumps(response))
                except json.JSONDecodeError:
                    logger.warning(f"Bad message: {raw_msg[:100]}")
                except Exception as e:
                    logger.error(f"Handler error: {e}")
                    await websocket.send(json.dumps({
                        "type": "text",
                        "token": "Sorry, I had an error.",
                        "last": True
                    }))
        except Exception as e:
            logger.info(f"Connection closed: {e}")

    def run(self):
        """Start the WebSocket server (blocking)."""
        asyncio.run(self._start())

    async def _start(self):
        try:
            import websockets
        except ImportError:
            raise RuntimeError("Run: pip install websockets")

        logger.info(f"ConversationRelay server starting on ws://{self.host}:{self.port}")
        async with websockets.serve(self._handle_connection, self.host, self.port):
            await asyncio.Future()  # Run forever
