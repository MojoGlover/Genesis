"""
voice_input — Microphone capture + speech-to-text for the cognitive loop.

Provides an input_feed that listens on the mic, transcribes speech via
Whisper (local, offline) and pushes the result into the Router.

Strategy:
  PRIMARY:  faster-whisper (local, no API, runs on CPU or GPU)
  FALLBACK: SpeechRecognition + Google (requires internet, free tier)
  SILENT:   If neither is available, logs a warning and does nothing.
            The agent still runs — just no voice input.

Install deps (add to requirements.txt):
    faster-whisper
    sounddevice
    numpy
    SpeechRecognition   (fallback only)

Config keys (under modules.voice_input in config.yaml):
    model_size:   whisper model size — "tiny", "base", "small" (default: "base")
                  "tiny" is fastest, "small" is more accurate
    language:     BCP-47 language code (default: "en")
    silence_threshold_db: dB below which audio is considered silence (default: -40)
    silence_duration_s:   seconds of silence to end an utterance (default: 1.5)
    max_duration_s:       max recording length in seconds (default: 30)
    device_index:         mic device index, None = system default

Returns:
    {
        "input_feed": [attach_fn],
        "capabilities": ["voice_input"],
    }
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST = {
    "name": "voice_input",
    "description": "Microphone → Whisper → router.ingest() voice input feed",
    "requires_credentials": [],
    "optional_credentials": [],
    "requires_config": [],
    "provides": ["input_feed"],
    "capabilities": ["voice_input"],
}

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULTS = {
    "model_size":           "base",
    "language":             "en",
    "silence_threshold_db": -40.0,
    "silence_duration_s":   1.5,
    "max_duration_s":       30,
    "device_index":         None,
    "sample_rate":          16000,
    "chunk_duration_s":     0.5,
}


# ── Whisper transcriber ───────────────────────────────────────────────────────

class _WhisperTranscriber:
    """Wraps faster-whisper for local offline transcription."""

    def __init__(self, model_size: str, language: str) -> None:
        self._language = language
        self._model = None
        try:
            from faster_whisper import WhisperModel
            logger.info(f"VoiceInput: loading Whisper model '{model_size}'...")
            self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
            logger.info("VoiceInput: Whisper model ready.")
        except ImportError:
            logger.warning("VoiceInput: faster-whisper not installed. pip install faster-whisper")
        except Exception as e:
            logger.warning(f"VoiceInput: could not load Whisper model: {e}")

    @property
    def available(self) -> bool:
        return self._model is not None

    def transcribe(self, audio_path: str) -> str:
        if not self._model:
            return ""
        try:
            segments, _ = self._model.transcribe(
                audio_path,
                language=self._language,
                beam_size=5,
                vad_filter=True,
            )
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            logger.error(f"VoiceInput: transcription failed: {e}")
            return ""


class _GoogleFallbackTranscriber:
    """SpeechRecognition + Google as fallback when Whisper not available."""

    def __init__(self, language: str) -> None:
        self._language = language
        self._sr = None
        try:
            import speech_recognition as sr
            self._sr = sr
            logger.info("VoiceInput: using Google fallback transcriber.")
        except ImportError:
            logger.warning("VoiceInput: SpeechRecognition not installed. pip install SpeechRecognition")

    @property
    def available(self) -> bool:
        return self._sr is not None

    def transcribe(self, audio_path: str) -> str:
        if not self._sr:
            return ""
        try:
            r = self._sr.Recognizer()
            with self._sr.AudioFile(audio_path) as source:
                audio = r.record(source)
            return r.recognize_google(audio, language=self._language)
        except self._sr.UnknownValueError:
            return ""
        except Exception as e:
            logger.error(f"VoiceInput: Google fallback failed: {e}")
            return ""


# ── VAD + recorder ────────────────────────────────────────────────────────────

def _record_utterance(cfg: dict) -> str | None:
    """
    Record from mic until silence is detected or max duration reached.
    Saves to a temp WAV file and returns the path, or None on failure.
    """
    try:
        import sounddevice as sd
        import numpy as np
        import tempfile
        import wave
    except ImportError as e:
        logger.warning(f"VoiceInput: missing audio dependency: {e}. pip install sounddevice numpy")
        return None

    sample_rate    = cfg["sample_rate"]
    chunk_dur      = cfg["chunk_duration_s"]
    silence_thresh = cfg["silence_threshold_db"]
    silence_dur    = cfg["silence_duration_s"]
    max_dur        = cfg["max_duration_s"]
    device         = cfg["device_index"]

    chunk_size  = int(sample_rate * chunk_dur)
    chunks: list = []
    silent_time = 0.0
    total_time  = 0.0
    speaking    = False

    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=chunk_size,
            device=device,
        ) as stream:
            logger.debug("VoiceInput: listening...")
            while total_time < max_dur:
                chunk, _ = stream.read(chunk_size)
                total_time += chunk_dur

                # RMS → dB
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                db  = 20 * np.log10(rms + 1e-9)

                if db > silence_thresh:
                    speaking = True
                    silent_time = 0.0
                    chunks.append(chunk.copy())
                elif speaking:
                    chunks.append(chunk.copy())
                    silent_time += chunk_dur
                    if silent_time >= silence_dur:
                        break

        if not chunks or not speaking:
            return None

        # Write WAV
        audio = np.concatenate(chunks, axis=0)
        audio_int16 = (audio * 32767).astype(np.int16)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        return tmp.name

    except Exception as e:
        logger.error(f"VoiceInput: recording failed: {e}")
        return None


# ── Input feed factory ────────────────────────────────────────────────────────

def _make_voice_feeder(cfg: dict, transcriber: Any) -> callable:
    """Returns an attach_fn(router) that starts the voice capture loop."""

    def attach(router) -> None:
        def _voice_loop():
            import os
            logger.info("VoiceInput: voice input loop started.")
            while True:
                try:
                    audio_path = _record_utterance(cfg)
                    if not audio_path:
                        time.sleep(0.1)
                        continue

                    text = transcriber.transcribe(audio_path)

                    try:
                        os.unlink(audio_path)
                    except Exception:
                        pass

                    text = text.strip()
                    if not text:
                        continue

                    logger.info(f"VoiceInput: heard: {text!r}")
                    router.ingest(text, channel="voice")

                except Exception as e:
                    logger.error(f"VoiceInput: loop error: {e}")
                    time.sleep(1.0)

        t = threading.Thread(target=_voice_loop, daemon=True, name="voice_input")
        t.start()
        logger.info("VoiceInput: voice capture thread started.")

    return attach


# ── Module entry point ────────────────────────────────────────────────────────

def setup(config: dict) -> dict:
    """Module entry point. Called by the loader."""
    registry = None
    try:
        from modules.module_manifest import registry as _registry
        registry = _registry
        registry.register("voice_input", MANIFEST, status="pending")
    except ImportError:
        # Module manifest not available in this agent
        pass

    module_cfg = config.get("modules", {}).get("voice_input", {})
    cfg = {**_DEFAULTS, **module_cfg}

    # Pick best available transcriber
    whisper = _WhisperTranscriber(cfg["model_size"], cfg["language"])
    if whisper.available:
        transcriber = whisper
        if registry:
            registry.mark_active("voice_input")
    else:
        fallback = _GoogleFallbackTranscriber(cfg["language"])
        if fallback.available:
            transcriber = fallback
            if registry:
                registry.mark_active("voice_input")
        else:
            logger.warning(
                "VoiceInput: no transcriber available. "
                "Install faster-whisper or SpeechRecognition to enable voice input."
            )
            return {"input_feed": [], "capabilities": []}

    return {
        "input_feed":   [_make_voice_feeder(cfg, transcriber)],
        "capabilities": ["voice_input"],
    }
