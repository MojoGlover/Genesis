"""
Task Detection Service - LLM-based task readiness detection
Replaces gradio_interface.py lines 51-101 (_detect_task_ready)
"""

import json
import logging
from typing import Dict, Any, List, Optional

from core.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)

TASK_DETECTION_PROMPT = """Analyze if the conversation has defined a COMPLETE, ACTIONABLE task.

A task is ready if:
- User has clearly described WHAT to build
- Sufficient details provided (or reasonable defaults possible)
- User intent is to CREATE something (not just discuss)

NOT ready if:
- Still asking questions/exploring
- Vague or ambiguous
- Just discussing possibilities

If ready, respond with JSON:
{
  "ready": true,
  "name": "Short task name",
  "description": "What it does",
  "details": "Key requirements/features",
  "estimated_file": "suggested_filename.py"
}

If not ready, respond: {"ready": false}"""


class TaskDetectionService:
    """Detects when a conversation has defined a clear, actionable task"""

    def __init__(self):
        self._llm = get_llm_service()

    def detect(
        self,
        message: str,
        conversation_context: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """Detect if the conversation has defined a task ready for queuing.

        Args:
            message: Current user message
            conversation_context: Recent conversation [{role, content}, ...]

        Returns:
            {"success": bool, "ready": bool, "task": dict | None}
        """
        if not self._llm.available:
            return {"success": False, "ready": False, "task": None}

        try:
            # Build messages: system + recent context + current message
            messages = list(conversation_context[-6:])
            messages.append({"role": "user", "content": message})

            result = self._llm.generate_chat(
                messages=messages,
                system_prompt=TASK_DETECTION_PROMPT,
                temperature=0.3,
                max_tokens=300,
            )

            if not result.get("success"):
                return {"success": False, "ready": False, "task": None}

            content = result.get("content", "")
            parsed = json.loads(content)

            if parsed.get("ready"):
                task = {
                    "name": parsed.get("name", ""),
                    "description": parsed.get("description", ""),
                    "details": parsed.get("details", ""),
                    "estimated_file": parsed.get("estimated_file", "script.py"),
                }
                logger.info(f"Task detected: {task['name']}")
                return {"success": True, "ready": True, "task": task}

            return {"success": True, "ready": False, "task": None}

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Task detection parse error: {e}")
            return {"success": False, "ready": False, "task": None}
        except Exception as e:
            logger.error(f"Task detection error: {e}")
            return {"success": False, "ready": False, "task": None}


# Singleton
_task_detection_service = None


def get_task_detection_service() -> TaskDetectionService:
    """Get or create TaskDetectionService singleton"""
    global _task_detection_service
    if _task_detection_service is None:
        _task_detection_service = TaskDetectionService()
    return _task_detection_service
