"""SMS Notifications - send alerts and receive tasks via SMS"""
from __future__ import annotations
import logging
from typing import Optional, List
from datetime import datetime
from .client import TwilioClient, TwilioConfig

logger = logging.getLogger(__name__)


class SMSNotifier:
    """
    Send SMS alerts to your phone from Engineer0.
    
    Use cases:
    - Task completed: "✅ Task #123 done: wrote auth module"
    - Error alert: "⚠️ Engineer0 needs help: <error>"
    - Daily digest: summary of what was accomplished
    - Inbound SMS → add task to Engineer0 queue
    """

    def __init__(self, client: Optional[TwilioClient] = None, config: Optional[TwilioConfig] = None):
        self.twilio = client or TwilioClient(config)

    def send(self, message: str, to: Optional[str] = None) -> dict:
        """Send an SMS. Returns {success, sid, error}"""
        if not self.twilio.is_configured():
            return {"success": False, "error": "Twilio not configured — set TWILIO_* env vars"}
        try:
            to_num = to or self.twilio.config.to_number
            msg = self.twilio.client.messages.create(
                body=message[:1600],  # SMS limit
                from_=self.twilio.config.from_number,
                to=to_num,
            )
            logger.info(f"SMS sent: {msg.sid}")
            return {"success": True, "sid": msg.sid, "to": to_num}
        except Exception as e:
            logger.error(f"SMS failed: {e}")
            return {"success": False, "error": str(e)}

    def alert_task_complete(self, task_id: str, description: str, result: str = "") -> dict:
        """Notify when an Engineer0 task completes."""
        msg = f"✅ Engineer0\nTask #{task_id[:8]} done\n{description[:100]}"
        if result:
            msg += f"\n\n{result[:200]}"
        return self.send(msg)

    def alert_error(self, error: str, context: str = "") -> dict:
        """Notify on critical error."""
        msg = f"⚠️ Engineer0 Error\n{error[:200]}"
        if context:
            msg += f"\n\nContext: {context[:100]}"
        return self.send(msg)

    def send_digest(self, completed: List[str], failed: List[str], learnings: List[str] = []) -> dict:
        """Daily digest SMS."""
        lines = [
            f"📊 Engineer0 Digest {datetime.now().strftime('%m/%d %H:%M')}",
            f"✅ {len(completed)} completed",
            f"❌ {len(failed)} failed",
        ]
        if completed:
            lines.append("\nDone:")
            lines.extend([f"  • {t[:60]}" for t in completed[:3]])
        if failed:
            lines.append("\nFailed:")
            lines.extend([f"  • {t[:60]}" for t in failed[:2]])
        if learnings:
            lines.append(f"\n🧠 {len(learnings)} new learnings")
        return self.send("\n".join(lines))

    def parse_inbound(self, request_body: dict) -> dict:
        """
        Parse an inbound SMS webhook from Twilio.
        Wire this to your Flask endpoint: POST /twilio/sms/inbound
        
        Returns: {from_number, body, command, task_text}
        """
        body = request_body.get("Body", "").strip()
        from_num = request_body.get("From", "")
        
        result = {"from_number": from_num, "body": body, "command": None, "task_text": None}
        
        # Parse commands from SMS
        lower = body.lower()
        if lower.startswith("task:") or lower.startswith("do:"):
            result["command"] = "add_task"
            result["task_text"] = body.split(":", 1)[1].strip()
        elif lower.startswith("status"):
            result["command"] = "status"
        elif lower.startswith("stop") or lower.startswith("pause"):
            result["command"] = "pause"
        elif lower.startswith("go") or lower.startswith("resume"):
            result["command"] = "resume"
        elif lower.startswith("learn:"):
            result["command"] = "learn"
            result["task_text"] = body.split(":", 1)[1].strip()
        else:
            result["command"] = "chat"
            result["task_text"] = body
            
        return result

    def reply_twiml(self, message: str) -> str:
        """Generate TwiML XML response for inbound SMS."""
        safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{safe[:1600]}</Message>
</Response>"""
