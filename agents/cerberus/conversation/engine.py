"""
engine.py — Base conversation engine for BlackZero agents.

Handles the shared mechanics of multi-turn conversation:
  - Smart context window (not dumb slice)
  - Intent classification hooks
  - Response preparation pipeline
  - Memory injection
  - Activity-aware system prompt enrichment

Each agent subclasses ConversationEngine and overrides what's different.
The engine doesn't know about TTS, networking, or UI — those are agent concerns.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from .voice_profile import VoiceProfile


# ── Message types ──────────────────────────────────────────────────────────────

@dataclass
class Turn:
    role:      str   # 'user' | 'assistant' | 'system'
    content:   str
    timestamp: float = field(default_factory=time.time)
    intent:    str   = ''     # classified intent, if known
    important: bool  = False  # flag to keep in context even when old


# ── Intent classification ──────────────────────────────────────────────────────

# Pattern banks — shared baseline. Agents can extend via register_intent().
_BASE_INTENTS: list[tuple[str, list[re.Pattern]]] = [
    ('memory_request', [
        re.compile(r'^remember\b', re.I),
        re.compile(r"\bdon'?t forget\b", re.I),
        re.compile(r'\bremind me\b', re.I),
        re.compile(r'\bnote that\b', re.I),
    ]),
    ('system_command', [
        re.compile(r'^(pause|stop|quiet|resume|continue)\b', re.I),
        re.compile(r"\blet'?s go\b", re.I),
    ]),
    ('clarification', [
        re.compile(r'\b(what do you mean|can you clarify|explain that)\b', re.I),
        re.compile(r'\b(i don\'?t understand|say that again)\b', re.I),
    ]),
    ('feedback', [
        re.compile(r'\b(wrong|incorrect|that\'?s not right)\b', re.I),
        re.compile(r'\b(good|correct|exactly|perfect|right answer)\b', re.I),
        re.compile(r'\btry again\b', re.I),
    ]),
    ('question', [
        re.compile(r'^(what|where|when|who|why|how|which|is|are|can|does|do|will)\b', re.I),
        re.compile(r'\?$'),
    ]),
]


def classify_intent(text: str, extra_intents: list | None = None) -> str:
    """Simple pattern-based intent classifier. Returns intent string."""
    all_intents = _BASE_INTENTS + (extra_intents or [])
    best: tuple[str, int] = ('conversation', 0)
    for intent_name, patterns in all_intents:
        hits = sum(1 for p in patterns if p.search(text))
        if hits > best[1]:
            best = (intent_name, hits)
    return best[0]


# ── Context window builder ─────────────────────────────────────────────────────

def build_context_window(
    history: list[Turn],
    max_turns: int = 12,
    max_chars: int = 4000,
) -> list[Turn]:
    """
    Smarter than slice(-N):
      - Always keeps 'important' turns regardless of age
      - Fills remaining budget from most recent turns
      - Hard cap at max_chars total
    """
    important = [t for t in history if t.important]
    recent    = [t for t in history if not t.important][-max_turns:]

    # Merge, deduplicate, keep order
    seen_ids = set()
    merged: list[Turn] = []
    for turn in important + recent:
        tid = id(turn)
        if tid not in seen_ids:
            seen_ids.add(tid)
            merged.append(turn)
    merged.sort(key=lambda t: t.timestamp)

    # Trim to char budget
    total = 0
    trimmed: list[Turn] = []
    for turn in reversed(merged):
        total += len(turn.content)
        if total > max_chars and trimmed:
            break
        trimmed.append(turn)
    trimmed.reverse()
    return trimmed


def compress_older_turns(turns: list[Turn]) -> str:
    """Summarize older turns into a brief note for the system message."""
    if not turns:
        return ''
    user_msgs = [t.content[:80] for t in turns if t.role == 'user'][:4]
    if not user_msgs:
        return ''
    return f'[Earlier in conversation: {" / ".join(user_msgs)}]'


# ── Conversation engine ────────────────────────────────────────────────────────

class ConversationEngine:
    """
    Base conversation engine. Agents subclass this.

    Usage:
        engine = ConversationEngine(profile=MyAgentProfile())
        messages = engine.build_messages(user_input, system_ctx='on route')
        response = llm.chat(messages)
        engine.record(user_input, response)
    """

    def __init__(
        self,
        profile: VoiceProfile,
        max_turns: int = 12,
        max_context_chars: int = 4000,
        extra_intents: list | None = None,
    ) -> None:
        self.profile = profile
        self.max_turns = max_turns
        self.max_context_chars = max_context_chars
        self.extra_intents = extra_intents or []
        self.history: list[Turn] = []
        self._memory_fn: Optional[Callable[[], str]] = None

    def set_memory_fn(self, fn: Callable[[], str]) -> None:
        """Register an async-safe function that returns memory context string."""
        self._memory_fn = fn

    def record(self, user_input: str, response: str) -> None:
        """Add a completed turn to history."""
        intent = classify_intent(user_input, self.extra_intents)
        self.history.append(Turn(role='user', content=user_input, intent=intent))
        self.history.append(Turn(role='assistant', content=response))
        # Keep history bounded
        if len(self.history) > 200:
            self.history = self.history[-200:]

    def mark_important(self, content_snippet: str) -> None:
        """Flag a turn as important so it's never dropped from context."""
        for turn in self.history:
            if content_snippet in turn.content:
                turn.important = True

    def build_messages(
        self,
        user_input: str,
        system_context: str = '',
        memory_context: str = '',
    ) -> list[dict[str, str]]:
        """
        Build the message list to send to the LLM.
        Returns list of {role, content} dicts (OpenAI/Anthropic format).
        """
        # Classify intent for this input
        intent = classify_intent(user_input, self.extra_intents)

        # Build system message
        system_parts = [self.profile.system_prompt_voice_section()]
        if system_context:
            system_parts.append(system_context)
        if memory_context:
            system_parts.append(memory_context)

        # Compress old history into system message
        window = build_context_window(self.history, self.max_turns, self.max_context_chars)
        older  = [t for t in self.history if t not in window]
        if older:
            summary = compress_older_turns(older)
            if summary:
                system_parts.append(summary)

        system_msg = '\n\n'.join(p for p in system_parts if p)

        # Assemble messages
        messages: list[dict[str, str]] = [{'role': 'system', 'content': system_msg}]
        for turn in window:
            if turn.role in ('user', 'assistant'):
                messages.append({'role': turn.role, 'content': turn.content})
        messages.append({'role': 'user', 'content': user_input})

        return messages

    def prepare_response(self, raw: str) -> str:
        """Run LLM output through the agent's voice profile pipeline."""
        return self.profile.prepare(raw)

    def clear(self) -> None:
        self.history = []
