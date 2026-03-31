"""
voice_profile.py — Base voice profile for BlackZero agents.

Every agent built in GENESIS gets a voice profile. This base class
defines the shared contract. Each agent extends it in their own
voice/ folder with their specific personality, pace, and TTS config.

The base profile has no gender, no accent, no catch phrases.
That's intentional — this is the foundation. Personality layers on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from .fluency import prepare_for_speech


@dataclass
class VoiceProfile:
    """
    Base voice profile. Override in each agent's voice/profile.py.

    Attributes:
        name:           Agent's name (used in self-references)
        formality:      'casual' | 'professional' | 'technical'
        pace:           'slow' | 'normal' | 'fast' — influences TTS speed
        verbosity:      'concise' | 'moderate' | 'detailed'
        max_speech_chars: Hard limit for spoken responses (0 = no limit)
        ssml:           Whether to emit SSML break tags (ElevenLabs, Google)
        tts_provider:   'elevenlabs' | 'expo' | 'system' | 'none'
        tts_voice_id:   Provider-specific voice ID
        personality_notes: Free-form guidance for the LLM system prompt
    """
    name:               str   = 'Agent'
    formality:          str   = 'professional'
    pace:               str   = 'normal'
    verbosity:          str   = 'concise'
    max_speech_chars:   int   = 500
    ssml:               bool  = False
    tts_provider:       str   = 'system'
    tts_voice_id:       str   = ''
    personality_notes:  str   = ''

    # Vocabulary preferences — words to prefer / avoid in speech
    preferred_words:    list  = field(default_factory=list)
    avoided_words:      list  = field(default_factory=list)

    def prepare(self, text: str) -> str:
        """
        Run text through the shared fluency pipeline with this profile's settings.
        Override in subclasses to add agent-specific post-processing.
        """
        cleaned = prepare_for_speech(
            text,
            remove_sycophancy=True,
            naturalize_nums=(self.formality != 'technical'),
            ssml=self.ssml,
            max_chars=self.max_speech_chars if self.max_speech_chars > 0 else 0,
        )
        return self._apply_vocabulary(cleaned)

    def _apply_vocabulary(self, text: str) -> str:
        """Swap avoided words for preferred alternatives if defined."""
        # Subclasses override this with agent-specific substitutions
        return text

    def system_prompt_voice_section(self) -> str:
        """
        Returns a voice/style section to append to the agent's system prompt.
        Tells the LLM how this agent should speak.
        """
        lines = [
            f'Your name is {self.name}.',
            f'Communication style: {self.formality}.',
            f'Response length: {self.verbosity} — avoid unnecessary padding.',
            'You are being spoken aloud via text-to-speech. Do not use markdown, '
            'bullet points, numbered lists, or code formatting in spoken responses. '
            'Use plain, natural spoken language.',
            'Do not open with sycophantic phrases like "Certainly!", "Great question!", '
            'or "Of course!". Get straight to the point.',
        ]
        if self.verbosity == 'concise':
            lines.append('Keep responses under 3 sentences unless the question genuinely requires more.')
        if self.personality_notes:
            lines.append(self.personality_notes)
        if self.avoided_words:
            lines.append(f'Avoid these words: {", ".join(self.avoided_words)}.')
        return '\n'.join(lines)

    def describe(self) -> str:
        return (
            f'{self.name} | {self.formality} | {self.pace} pace | '
            f'{self.verbosity} | TTS: {self.tts_provider}'
        )
