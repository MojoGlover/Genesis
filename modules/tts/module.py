"""
tts — Text-to-speech output for the cognitive loop.

Provides a sink that speaks agent responses aloud.

Strategy:
  PRIMARY:  ElevenLabs API (high-quality, requires ELEVENLABS_API_KEY)
  FALLBACK: macOS `say` command (offline, built-in, free)
  SILENT:   If neither is available, logs a warning and does nothing.
            The agent still runs — just no voice output.

Install deps (add to requirements.txt):
    requests   (usually already present)

Config keys (under modules.tts in config.yaml):
    voice_id:       ElevenLabs voice ID (default: "Rachel" preset)
    model_id:       ElevenLabs model (default: "eleven_turbo_v2")
    speed:          macOS `say` rate in words/min (default: 175)
    max_chars:      Truncate text longer than this before speaking (default: 500)
    mute:           Set true to silence TTS without unloading the module (default: false)

Returns:
    {
        "sinks":        [sink_fn],
        "capabilities": ["tts"],
    }
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST = {
    "name": "tts",
    "description": "Text-to-speech output — ElevenLabs (primary) or macOS say (fallback)",
    "requires_credentials": [],
    "optional_credentials": ["ELEVENLABS_API_KEY"],
    "requires_config": [],
    "provides": ["sinks"],
    "capabilities": ["tts"],
}

_DEFAULTS = {
    "voice_id":   "21m00Tcm4TlvDq8ikWAM",   # ElevenLabs "Rachel"
    "model_id":   "eleven_turbo_v2",
    "speed":      175,                         # macOS say words/min
    "max_chars":  500,
    "mute":       False,
}

_ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

# One speech job at a time — prevent overlapping audio
_speak_lock = threading.Lock()


# ── ElevenLabs speaker ────────────────────────────────────────────────────────

class _ElevenLabsSpeaker:
    """Streams TTS audio from ElevenLabs and plays it via afplay (macOS)."""

    def __init__(self, api_key: str, voice_id: str, model_id: str) -> None:
        self._api_key  = api_key
        self._voice_id = voice_id
        self._model_id = model_id

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def speak(self, text: str) -> None:
        import tempfile, requests  # noqa: E401
        try:
            url = _ELEVENLABS_URL.format(voice_id=self._voice_id)
            headers = {
                "xi-api-key":   self._api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "text":       text,
                "model_id":   self._model_id,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()

            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(resp.content)
            tmp.flush()
            tmp.close()

            subprocess.run(["afplay", tmp.name], check=True)
            os.unlink(tmp.name)

        except Exception as e:
            logger.error(f"TTS ElevenLabs: speak failed: {e}")
            raise


# ── macOS say speaker ─────────────────────────────────────────────────────────

class _MacSaySpeaker:
    """Uses the built-in macOS `say` command — zero dependencies, offline."""

    def __init__(self, speed: int) -> None:
        self._speed = speed
        self._available = self._check()

    def _check(self) -> bool:
        try:
            subprocess.run(["say", "--version"], capture_output=True, timeout=3)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @property
    def available(self) -> bool:
        return self._available

    def speak(self, text: str) -> None:
        try:
            subprocess.run(
                ["say", "-r", str(self._speed), text],
                check=True,
                timeout=60,
            )
        except Exception as e:
            logger.error(f"TTS macOS say: speak failed: {e}")
            raise


# ── Sink factory ─────────────────────────────────────────────────────────────

def _make_tts_sink(cfg: dict, speaker: Any) -> callable:
    """Returns a sink_fn(message, router) that speaks the message text."""

    max_chars = cfg["max_chars"]
    mute      = cfg["mute"]

    def sink(message: dict, router=None) -> None:  # noqa: ARG001
        if mute:
            return

        text = ""
        if isinstance(message, str):
            text = message
        elif isinstance(message, dict):
            text = message.get("text") or message.get("content") or message.get("response") or ""

        text = text.strip()
        if not text:
            return

        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "…"

        # Non-blocking — speak in a background thread so the loop doesn't stall
        def _speak():
            with _speak_lock:
                try:
                    speaker.speak(text)
                except Exception:
                    pass  # already logged in speaker.speak()

        t = threading.Thread(target=_speak, daemon=True, name="tts_speak")
        t.start()

    return sink


# ── Module entry point ────────────────────────────────────────────────────────

def setup(config: dict) -> dict:
    """Module entry point. Called by the loader."""
    registry = None
    try:
        from modules.module_manifest import registry as _registry
        registry = _registry
        registry.register("tts", MANIFEST, status="pending")
    except ImportError:
        # Module manifest not available in this agent
        pass

    module_cfg = config.get("modules", {}).get("tts", {})
    cfg = {**_DEFAULTS, **module_cfg}

    # Try ElevenLabs first
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if api_key:
        try:
            import requests  # noqa: F401 — just check it's installed
            speaker = _ElevenLabsSpeaker(api_key, cfg["voice_id"], cfg["model_id"])
            if registry:
                registry.mark_active("tts")
            logger.info("TTS: using ElevenLabs.")
            return {
                "sinks": {"tts": _make_tts_sink(cfg, speaker)},
            }
        except ImportError:
            logger.warning("TTS: 'requests' not installed — can't use ElevenLabs. pip install requests")

    # Fall back to macOS say
    speaker = _MacSaySpeaker(cfg["speed"])
    if speaker.available:
        if registry:
            registry.mark_active("tts")
        logger.info("TTS: using macOS say (fallback).")
        return {
            "sinks": {"tts": _make_tts_sink(cfg, speaker)},
        }

    logger.warning(
        "TTS: no speaker available. "
        "Set ELEVENLABS_API_KEY or run on macOS to enable voice output."
    )
    return {}
