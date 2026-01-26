"""
Chat Service - Conversational response generation
Replaces gradio_interface.py lines 103-198 (_generate_conversational_response)
"""

import logging
from typing import Dict, Any, List

from core.services.llm_service import get_llm_service
from core.mission import get_system_prompt

logger = logging.getLogger(__name__)

GENESIS_SYSTEM_PROMPT = """You are GENESIS, a conversational AI coding assistant with autonomous execution capabilities.

YOUR CAPABILITIES:
You have access to a comprehensive tool system. At the start of any complex task, you should:
1. Call get_tool_summary() to see all available tools
2. Use tools to accomplish tasks - you are NOT limited to just conversation

YOUR TOOLS INCLUDE:
- FILE OPERATIONS: read, write, replace, delete, copy files and directories
- CODE EXECUTION: run Python code, capture output, parse errors, test iteratively
- PACKAGE MANAGEMENT: install dependencies, check packages, auto-install missing imports
- WORKSPACE: sandboxed environment for safe testing and file management

YOUR WORKFLOW:
1. Discuss and clarify requirements with the user
2. When user says "build it" -> task goes to queue
3. When "Execute Task" is clicked -> you autonomously:
   a. Use tool discovery to understand your capabilities
   b. Write the code
   c. Save to workspace
   d. Test execution
   e. Parse any errors
   f. Auto-install missing packages
   g. Fix errors iteratively
   h. Deliver working code

AUTONOMOUS EXECUTION PHILOSOPHY:
- You CAN and SHOULD execute code to verify it works
- You CAN and SHOULD install missing packages automatically
- You CAN and SHOULD fix errors iteratively without asking for help
- You work in a safe workspace sandbox
- You test -> detect errors -> fix -> test again until it works
- You don't just write code, you deliver WORKING code

COMMUNICATION:
- Chat naturally to understand requirements
- Keep responses concise (2-4 sentences)
- When task is ready, remind user they can say "build it"
- During execution, work autonomously and report results

Remember: You're an AUTONOMOUS agent. Use your tools. Make things work."""


class ChatService:
    """Generates conversational responses using LLM + mission context"""

    def __init__(self):
        self._llm = get_llm_service()

    def generate_response(
        self,
        message: str,
        conversation_context: List[Dict[str, str]],
        max_context_messages: int = 10,
    ) -> Dict[str, Any]:
        """Generate a conversational response.

        Args:
            message: The user's current message
            conversation_context: Recent conversation as [{role, content}, ...]
            max_context_messages: Max context messages to include

        Returns:
            {"success": bool, "content": str, "model": str}
        """
        if not self._llm.available:
            return {
                "success": True,
                "content": "I'm a coding assistant. I can help you build applications!",
                "model": "fallback",
            }

        try:
            system_prompt = get_system_prompt(GENESIS_SYSTEM_PROMPT)

            # Build message list: recent context + current message
            messages = list(conversation_context[-max_context_messages:])
            messages.append({"role": "user", "content": message})

            result = self._llm.generate_chat(
                messages=messages,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=300,
            )

            if result.get("success"):
                return {
                    "success": True,
                    "content": result["content"],
                    "model": result.get("model", "unknown"),
                }
            else:
                return {
                    "success": True,
                    "content": "I'm here to help you build things! What would you like to create?",
                    "model": "fallback",
                }

        except Exception as e:
            logger.error(f"Chat response error: {e}")
            return {
                "success": True,
                "content": "I'm here to help you build things! What would you like to create?",
                "model": "fallback",
            }


# Singleton
_chat_service = None


def get_chat_service() -> ChatService:
    """Get or create ChatService singleton"""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
