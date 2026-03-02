"""Ollama-based dialogue policy for Rasa."""
from typing import Any, Dict, List, Optional
import json
import urllib.request
from dataclasses import dataclass


@dataclass
class PolicyResponse:
    """Response from Ollama policy."""
    success: bool
    action: str
    confidence: float
    response_text: Optional[str] = None
    error: Optional[str] = None


class SimplifiedRasaAgent:
    """Simplified conversational agent using Ollama.
    
    Bypasses traditional Rasa complexity and uses Ollama directly
    for natural conversations.
    """
    
    def __init__(
        self,
        model: str = "genesis-zero:latest",
        ollama_url: str = "http://localhost:11434/api/generate"
    ):
        self.model = model
        self.ollama_url = ollama_url
        self.conversation_history: List[Dict[str, str]] = []
        self.system_prompt = """You are a helpful conversational assistant.

Rules:
- Be concise and natural
- Answer questions directly
- Be friendly but professional
- Keep responses under 3 sentences"""
    
    def process_message(self, user_message: str) -> str:
        """Process user message and return response.
        
        Args:
            user_message: User's input text
            
        Returns:
            Agent's response text
        """
        # Build conversation context
        context = self.system_prompt + "\n\nConversation:\n"
        
        for turn in self.conversation_history[-6:]:  # Last 6 messages
            role = "User" if turn["role"] == "user" else "Assistant"
            context += f"{role}: {turn['text']}\n"
        
        context += f"User: {user_message}\nAssistant:"
        
        # Get response from Ollama
        try:
            payload = {
                "model": self.model,
                "prompt": context,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9
                }
            }
            
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                self.ollama_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                response = result.get("response", "").strip()
        
        except Exception as e:
            response = f"Error: {str(e)}"
        
        # Update history
        self.conversation_history.append({"role": "user", "text": user_message})
        self.conversation_history.append({"role": "assistant", "text": response})
        
        # Trim history
        if len(self.conversation_history) > 12:
            self.conversation_history = self.conversation_history[-12:]
        
        return response
    
    def reset(self):
        """Reset conversation history."""
        self.conversation_history = []


# Alias for backwards compatibility
OllamaPolicy = SimplifiedRasaAgent
