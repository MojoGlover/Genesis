"""
Chat Orchestrator - Ties all services together with state machine
Replaces gradio_interface.py chat() method (lines 235-302) and state management
Any UI (Gradio, CLI, API, mobile) can use this orchestrator.
"""

import logging
from enum import Enum
from typing import Dict, Any, List, Optional

from core.services.llm_service import get_llm_service
from core.services.voice_service import get_voice_service
from core.services.workspace_service import get_workspace_service
from core.services.conversation_service import get_conversation_service
from core.services.chat_service import get_chat_service
from core.services.task_detection_service import get_task_detection_service
from core.services.task_execution_service import get_task_execution_service

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    READY = "ready"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"


class ChatOrchestrator:
    """Central orchestrator for GENESIS chat workflow.

    Returns structured data only — no HTML, no Gradio objects.
    """

    def __init__(self):
        self._voice = get_voice_service()
        self._workspace = get_workspace_service()
        self._conversation = get_conversation_service()
        self._chat = get_chat_service()
        self._task_detection = get_task_detection_service()
        self._task_execution = get_task_execution_service()

        self._state = ConversationState.READY
        self._pending_task: Optional[Dict[str, Any]] = None
        self._selected_task_id: Optional[str] = None

        # Start a session
        self._conversation.start_session()
        logger.info("ChatOrchestrator initialized")

    @property
    def state(self) -> ConversationState:
        return self._state

    def process_message(
        self,
        message: str,
        voice_input: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Primary entry point for any UI.

        Args:
            message: Text message from user
            voice_input: Optional audio file path

        Returns:
            {
                "response": str,          # Assistant's text reply
                "state": str,             # Current conversation state
                "task_ready": bool,       # Whether a task was detected
                "pending_task": dict|None, # Task awaiting confirmation
                "tasks": list,            # Current task queue
                "voice_audio": str|None,  # TTS audio path if available
            }
        """
        # Handle voice input
        if voice_input is not None:
            stt_result = self._voice.speech_to_text(voice_input)
            if stt_result.get("success") and stt_result.get("text"):
                message = stt_result["text"]

        if not message or not message.strip():
            return self._build_response("", state_override=None)

        # Record user message
        self._conversation.add_message("user", message)

        lower_msg = message.lower().strip()

        # Handle confirmation flow
        if self._state == ConversationState.AWAITING_CONFIRMATION:
            if lower_msg in ("yes", "y", "confirm", "do it"):
                return self._confirm_task()
            if lower_msg in ("no", "n", "cancel", "nevermind"):
                return self._cancel_task()

        # Handle "build it" type commands
        build_commands = ("build it", "create it", "do it", "make it", "go ahead")
        if any(cmd in lower_msg for cmd in build_commands):
            return self._handle_build_command(message)

        # Normal conversation
        return self._handle_conversation(message)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _handle_conversation(self, message: str) -> Dict[str, Any]:
        """Normal conversational turn"""
        context = self._conversation.get_context(limit=10)

        # Generate response
        chat_result = self._chat.generate_response(message, context)
        response_text = chat_result.get("content", "")

        # Detect if task is ready
        detection = self._task_detection.detect(message, context)
        task_ready = detection.get("ready", False)

        if task_ready:
            self._pending_task = detection.get("task")

        # Record assistant response
        self._conversation.add_message("assistant", response_text)

        # TTS
        voice_audio = None
        if self._voice.tts_available:
            tts_result = self._voice.text_to_speech(response_text)
            voice_audio = tts_result.get("audio_path")

        return self._build_response(
            response_text,
            task_ready=task_ready,
            voice_audio=voice_audio,
        )

    def _handle_build_command(self, message: str) -> Dict[str, Any]:
        """Handle 'build it' type commands"""
        context = self._conversation.get_context(limit=10)
        detection = self._task_detection.detect(message, context)

        if detection.get("ready") and detection.get("task"):
            self._pending_task = detection["task"]
            self._state = ConversationState.AWAITING_CONFIRMATION

            task_name = self._pending_task["name"]
            task_desc = self._pending_task["description"]
            response = f"I'll create: **{task_name}**\n{task_desc}\n\nConfirm? (yes/no)"

            self._conversation.add_message("assistant", response)

            return self._build_response(response)
        else:
            response = "I'm not sure exactly what to build yet. Can you describe what you want in more detail?"
            self._conversation.add_message("assistant", response)
            return self._build_response(response)

    def _confirm_task(self) -> Dict[str, Any]:
        """Confirm and add pending task to queue"""
        if not self._pending_task:
            self._state = ConversationState.READY
            response = "No task to confirm. What would you like to build?"
            self._conversation.add_message("assistant", response)
            return self._build_response(response)

        add_result = self._task_execution.add_task(self._pending_task)
        task_name = self._pending_task["name"]

        # Reset confirmation state
        self._state = ConversationState.READY
        self._pending_task = None

        if add_result.get("success"):
            response = f"Added to queue: **{task_name}**\nClick 'Execute Task' to generate code!"
        else:
            response = f"Failed to add task: {add_result.get('error', 'Queue full')}"

        self._conversation.add_message("assistant", response)

        voice_audio = None
        if self._voice.tts_available:
            tts_result = self._voice.text_to_speech(response)
            voice_audio = tts_result.get("audio_path")

        return self._build_response(response, voice_audio=voice_audio)

    def _cancel_task(self) -> Dict[str, Any]:
        """Cancel pending task confirmation"""
        self._state = ConversationState.READY
        self._pending_task = None
        response = "Okay, cancelled. What would you like to build?"
        self._conversation.add_message("assistant", response)
        return self._build_response(response)

    # ------------------------------------------------------------------
    # Public actions (for UI buttons)
    # ------------------------------------------------------------------

    def execute_task(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute a task from the queue.

        Returns:
            {"success": bool, "code": str, "iterations": int, "status": str, "execution_log": list}
        """
        tid = task_id or self._selected_task_id
        return self._task_execution.execute_task(tid)

    def select_task(self, task_choice: str) -> Dict[str, Any]:
        """Select a task from dropdown choice string.

        Returns:
            {"success": bool, "task_id": str, "details": str}
        """
        if not task_choice or task_choice == "No tasks":
            self._selected_task_id = None
            return {
                "success": False,
                "task_id": None,
                "details": "# No task selected\n# Queue a task to see details here",
            }

        try:
            task_id = task_choice.split(":")[0]
            task = self._task_execution.get_task(task_id)

            if not task:
                return {"success": False, "task_id": None, "details": "# Task not found"}

            self._selected_task_id = task_id

            details = f"""# Task: {task['name']}
# Status: {task['status'].title()}
# Created: {task.get('created_at', task.get('added_at', 'N/A'))}

\'\'\'
Description:
{task['description']}

Requirements:
{task['details']}

Estimated File: {task.get('estimated_file', 'script.py')}
\'\'\'

# Click 'Execute Task' to generate code for this task
"""
            return {"success": True, "task_id": task_id, "details": details}

        except Exception as e:
            logger.error(f"Error selecting task: {e}")
            return {"success": False, "task_id": None, "details": f"# Error: {e}"}

    def get_task_choices(self) -> List[str]:
        """Get formatted task list for dropdown"""
        return self._task_execution.get_task_choices()

    def get_latest_code(self) -> Dict[str, Any]:
        """Get latest code from workspace"""
        return self._workspace.get_latest_code()

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks in queue"""
        return self._task_execution.get_all_tasks()

    def reset(self) -> Dict[str, Any]:
        """Reset all state"""
        self._state = ConversationState.READY
        self._pending_task = None
        self._selected_task_id = None
        self._conversation.reset()
        self._conversation.start_session()
        return {"success": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_response(
        self,
        response: str,
        state_override: Optional[str] = None,
        task_ready: bool = False,
        voice_audio: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a standardized response dict"""
        return {
            "response": response,
            "state": state_override or self._state.value,
            "task_ready": task_ready,
            "pending_task": self._pending_task,
            "tasks": self._task_execution.get_all_tasks(),
            "voice_audio": voice_audio,
        }


# Singleton
_orchestrator = None


def get_orchestrator() -> ChatOrchestrator:
    """Get or create ChatOrchestrator singleton"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ChatOrchestrator()
    return _orchestrator
