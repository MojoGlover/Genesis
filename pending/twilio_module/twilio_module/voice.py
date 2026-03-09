"""Voice Bridge - make/receive calls, ConversationRelay for live AI phone calls"""
from __future__ import annotations
import logging
import json
from typing import Optional, Callable
from .client import TwilioClient, TwilioConfig

logger = logging.getLogger(__name__)


class VoiceBridge:
    """
    Phone call integration for Engineer0.
    
    Two modes:
    1. OUTBOUND: Engineer0 calls you to report something important
    2. INBOUND (ConversationRelay): You call a number → Engineer0 picks up and
       has a real-time voice conversation with you using your local LLM
    
    ConversationRelay flow:
    Phone call → Twilio → WebSocket → Engineer0 (STT→LLM→TTS) → back to phone
    """

    def __init__(self, client: Optional[TwilioClient] = None, config: Optional[TwilioConfig] = None):
        self.twilio = client or TwilioClient(config)

    def call_with_message(self, message: str, to: Optional[str] = None) -> dict:
        """
        Call your phone and speak a message (TTS).
        Engineer0 calls you when something critical happens.
        """
        if not self.twilio.is_configured():
            return {"success": False, "error": "Twilio not configured"}
        try:
            to_num = to or self.twilio.config.to_number
            safe_msg = message.replace("&", "and").replace("<", "").replace(">", "")
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna" rate="medium">{safe_msg[:3000]}</Say>
</Response>"""
            call = self.twilio.client.calls.create(
                twiml=twiml,
                to=to_num,
                from_=self.twilio.config.from_number,
            )
            logger.info(f"Call initiated: {call.sid}")
            return {"success": True, "call_sid": call.sid, "to": to_num}
        except Exception as e:
            logger.error(f"Call failed: {e}")
            return {"success": False, "error": str(e)}

    def generate_conversation_relay_twiml(self, websocket_url: str) -> str:
        """
        Generate TwiML that connects an inbound call to ConversationRelay.
        
        When someone calls your Twilio number, Twilio hits your /twilio/voice/inbound
        webhook. Return this TwiML to connect the call to your AI via WebSocket.
        
        The websocket_url should be your Engineer0 backend:
        e.g. wss://yourserver.com/twilio/voice/ws
        """
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <ConversationRelay url="{websocket_url}" 
                          welcomeGreeting="Engineer0 here. How can I help?" 
                          voice="en-US-Neural2-F"
                          ttsProvider="google"
                          transcriptionProvider="google"
                          speechModel="telephony"/>
    </Connect>
</Response>"""

    def generate_inbound_twiml(self, websocket_url: Optional[str] = None) -> str:
        """
        TwiML for inbound calls. Uses ConversationRelay if websocket_url set,
        otherwise falls back to a simple voicemail-style response.
        """
        if websocket_url:
            return self.generate_conversation_relay_twiml(websocket_url)
        return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Engineer Zero is not available right now. Leave a message after the tone.</Say>
    <Record maxLength="60" transcribe="true"/>
</Response>"""

    def handle_conversation_relay_message(self, msg: dict, ai_handler: Callable) -> dict:
        """
        Handle a single ConversationRelay WebSocket message from Twilio.
        
        msg types:
        - 'setup': call started, send welcome config
        - 'prompt': user spoke, text is in msg['voicePrompt'] — call ai_handler(text)
        - 'interrupt': user interrupted — abort current response
        - 'dtmf': keypad press
        
        Returns dict to send back over WebSocket.
        """
        msg_type = msg.get("type", "")
        
        if msg_type == "setup":
            return {
                "type": "config",
                "config": {
                    "welcomeGreeting": "Engineer Zero here. What do you need?",
                    "interruptible": True,
                    "voice": "en-US-Neural2-F",
                }
            }
        
        elif msg_type == "prompt":
            user_text = msg.get("voicePrompt", "").strip()
            if not user_text:
                return {"type": "text", "token": "I didn't catch that.", "last": True}
            
            logger.info(f"Caller said: {user_text}")
            
            # Call the AI handler (Engineer0's chat function)
            try:
                response_text = ai_handler(user_text)
                return {
                    "type": "text",
                    "token": response_text,
                    "last": True,
                }
            except Exception as e:
                return {"type": "text", "token": f"Error processing request: {str(e)}", "last": True}
        
        elif msg_type == "interrupt":
            return {"type": "clear"}
        
        elif msg_type == "dtmf":
            digit = msg.get("digit", "")
            if digit == "0":
                return {"type": "text", "token": "Transferring to voicemail.", "last": True}
            return {"type": "text", "token": f"You pressed {digit}.", "last": True}
        
        return {}

    def get_recording_transcript(self, recording_sid: str) -> Optional[str]:
        """Fetch transcript of a recorded voicemail."""
        try:
            recordings = self.twilio.client.recordings.list(limit=20)
            for rec in recordings:
                if rec.sid == recording_sid:
                    transcriptions = self.twilio.client.transcriptions.list(limit=1)
                    if transcriptions:
                        return transcriptions[0].transcription_text
        except Exception as e:
            logger.error(f"Transcript fetch failed: {e}")
        return None
