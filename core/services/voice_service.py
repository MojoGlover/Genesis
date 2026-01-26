"""
Voice Service - STT (Whisper) + TTS (pyttsx3)
Replaces gradio_interface.py lines 200-233
"""

import logging
import tempfile
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class VoiceService:
    """Speech-to-text and text-to-speech capabilities"""

    def __init__(self):
        self._tts_engine = None
        self._tts_available = False
        self._stt_available = False
        self._init_tts()
        self._init_stt()

    def _init_tts(self):
        """Initialize text-to-speech engine"""
        try:
            import pyttsx3
            self._tts_engine = pyttsx3.init()
            self._tts_engine.setProperty("rate", 175)
            self._tts_engine.setProperty("volume", 0.9)
            self._tts_available = True
            logger.info("TTS (pyttsx3) initialized")
        except ImportError:
            logger.warning("pyttsx3 not installed - TTS disabled")
        except Exception as e:
            logger.warning(f"TTS init failed: {e}")

    def _init_stt(self):
        """Initialize speech-to-text (Whisper placeholder)"""
        # TODO: Implement actual Whisper STT initialization
        self._stt_available = False
        logger.info("STT not yet implemented (Whisper placeholder)")

    @property
    def tts_available(self) -> bool:
        return self._tts_available

    @property
    def stt_available(self) -> bool:
        return self._stt_available

    def speech_to_text(self, audio_path: Optional[str]) -> Dict[str, Any]:
        """Convert speech audio to text"""
        if audio_path is None:
            return {"success": False, "text": "", "error": "No audio provided"}

        if not self._stt_available:
            logger.info("Voice input received (STT not implemented yet)")
            return {"success": False, "text": "", "error": "STT not available"}

        try:
            # TODO: Implement actual Whisper STT
            return {"success": False, "text": "", "error": "STT not implemented"}
        except Exception as e:
            logger.error(f"Speech-to-text error: {e}")
            return {"success": False, "text": "", "error": str(e)}

    def text_to_speech(self, text: str) -> Dict[str, Any]:
        """Generate TTS audio file from text"""
        if not self._tts_available:
            return {"success": False, "audio_path": None, "error": "TTS not available"}

        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            self._tts_engine.save_to_file(text, temp_file.name)
            self._tts_engine.runAndWait()
            return {"success": True, "audio_path": temp_file.name}
        except Exception as e:
            logger.error(f"Text-to-speech error: {e}")
            return {"success": False, "audio_path": None, "error": str(e)}


# Singleton
_voice_service = None


def get_voice_service() -> VoiceService:
    """Get or create VoiceService singleton"""
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service
