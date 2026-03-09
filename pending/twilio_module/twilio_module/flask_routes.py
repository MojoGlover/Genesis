"""
Flask route blueprints for Twilio webhooks.
Add to Engineer0's Flask app:

    from twilio_module.flask_routes import twilio_bp
    app.register_blueprint(twilio_bp)
"""
from __future__ import annotations
import json
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def create_twilio_blueprint(
    sms_notifier=None,
    voice_bridge=None,
    ai_chat_fn: Optional[Callable] = None,
    websocket_url: str = ""
):
    """
    Create Flask blueprint for Twilio webhooks.
    
    ai_chat_fn: function(message: str) -> str  — your AI's chat handler
    websocket_url: wss://yourhost/twilio/voice/ws for ConversationRelay
    """
    try:
        from flask import Blueprint, request, Response
    except ImportError:
        raise RuntimeError("Flask required")

    bp = Blueprint("twilio", __name__, url_prefix="/twilio")

    @bp.route("/sms/inbound", methods=["POST"])
    def sms_inbound():
        """Receive inbound SMS from Twilio."""
        if not sms_notifier:
            return Response("Not configured", status=503)
        
        parsed = sms_notifier.parse_inbound(request.form.to_dict())
        command = parsed.get("command")
        text = parsed.get("task_text", "")
        
        reply = "Got it."
        
        if command == "status":
            reply = "Engineer0 is running. Use 'task: <description>' to add tasks."
        elif command == "add_task":
            reply = f"✅ Task queued: {text[:80]}"
            # Hook: engineer0.add_task(text) would go here
        elif command == "chat" and ai_chat_fn and text:
            try:
                reply = ai_chat_fn(text)[:1500]
            except Exception as e:
                reply = f"Error: {e}"
        elif command == "learn":
            reply = f"🧠 Noted: {text[:100]}"
        
        twiml = sms_notifier.reply_twiml(reply)
        return Response(twiml, mimetype="text/xml")

    @bp.route("/voice/inbound", methods=["POST"])
    def voice_inbound():
        """Handle inbound phone call — connect to ConversationRelay or voicemail."""
        if not voice_bridge:
            return Response("<Response><Say>Not configured.</Say></Response>", mimetype="text/xml")
        
        ws_url = websocket_url or ""
        twiml = voice_bridge.generate_inbound_twiml(ws_url or None)
        return Response(twiml, mimetype="text/xml")

    @bp.route("/voice/status", methods=["POST"])
    def voice_status():
        """Call status callback — log call completions."""
        status = request.form.get("CallStatus", "unknown")
        sid = request.form.get("CallSid", "")
        logger.info(f"Call {sid}: {status}")
        return Response("", status=204)

    return bp
