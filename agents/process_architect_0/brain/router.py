"""
router.py — The Router

Directs input and output to the correct internal destination.
Normalizes all inbound messages before they reach the planner.
Formats all outbound responses before they leave the agent.

The router is the boundary layer. Everything outside is untrusted.
Everything inside is normalized and typed.

NOTE: This file is locked. Do not rename, remove, or nest it.
"""
from __future__ import annotations

import logging
import queue
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Channel definitions
# ------------------------------------------------------------------

CHANNELS = {
    "user":     "Direct user interaction (chat, terminal, UI)",
    "api":      "Incoming API request from an external caller",
    "internal": "Agent-to-agent or subsystem message",
    "tool":     "Tool result being returned to the brain",
    "system":   "System-level signal (health check, shutdown, etc.)",
    "default":  "Fallback channel when type is unknown",
}

# Input type classification rules
# Maps keywords/patterns to input_type labels used by the planner
INPUT_TYPE_RULES: list[tuple[list[str], str]] = [
    (["?", "how ", "what ", "why ", "when ", "who ", "where ", "explain"], "question"),
    (["write ", "create ", "generate ", "make ", "build ", "draft "], "instruction"),
    (["def ", "class ", "function", "import ", "```", "code ", "script "], "code_request"),
    (["review ", "improve ", "refine ", "check ", "reflect ", "revise "], "reflection"),
    (["find ", "search ", "look up", "retrieve ", "fetch ", "get "], "data_request"),
]


# ------------------------------------------------------------------
# Message types
# ------------------------------------------------------------------

@dataclass
class InboundMessage:
    raw: Any
    channel: str
    input_type: str
    context: dict
    reply_channel: str
    received_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class OutboundMessage:
    output: Any
    channel: str
    formatted: str
    sent_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ------------------------------------------------------------------
# Router
# ------------------------------------------------------------------

class Router:
    """
    The I/O boundary of the agent.

    Inbound responsibilities:
    - Receive raw input from any channel
    - Strip external identity signals (models, APIs adding their own framing)
    - Classify the input type so the planner can choose a strategy
    - Normalize to a standard context dict

    Outbound responsibilities:
    - Format responses for the target channel
    - Route to the correct output sink (user, API, internal queue)
    - Log all traffic at the boundary

    What this does NOT do:
    - Make decisions (planner)
    - Execute actions (executor)
    - Run the loop (loop.py)
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._input_queue: queue.Queue = queue.Queue()
        self._output_sinks: dict[str, Any] = {}
        self._error_sink: Optional[Any] = None
        self._message_log: list[dict] = []
        logger.info("Router initialized.")

    # ------------------------------------------------------------------
    # Sink registration
    # ------------------------------------------------------------------

    def register_sink(self, channel: str, sink: Any) -> None:
        """
        Register an output sink for a channel.
        A sink is any callable that accepts (output: str).
        Example: register_sink("user", print)
        """
        self._output_sinks[channel] = sink
        logger.info(f"Output sink registered for channel '{channel}'.")

    def register_error_sink(self, sink: Any) -> None:
        self._error_sink = sink

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def receive(self) -> Optional[Any]:
        """
        Pull the next message from the input queue.
        Returns None if the queue is empty (non-blocking).
        """
        try:
            return self._input_queue.get_nowait()
        except queue.Empty:
            return None

    def receive_blocking(self, timeout: float = 1.0) -> Optional[Any]:
        """Blocking receive with timeout."""
        try:
            return self._input_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def ingest(self, raw_input: Any, channel: str = "user") -> None:
        """
        Push raw input into the queue from any external source.
        Called by the interface layer (API, UI, CLI, etc.).
        """
        self._input_queue.put({"raw": raw_input, "channel": channel})

    def classify_input(self, raw_input: Any) -> dict:
        """
        Normalize and classify incoming input.

        Returns a routed dict:
          {
            "type": str,           # input_type for planner
            "context": dict,       # normalized context
            "reply_channel": str,  # where to send the response
          }
        """
        # Unpack if it came through ingest()
        if isinstance(raw_input, dict) and "raw" in raw_input:
            channel = raw_input.get("channel", "default")
            raw = raw_input["raw"]
        else:
            channel = "default"
            raw = raw_input

        # Normalize to string for classification
        text = self._to_text(raw)

        # Strip external framing from the input itself
        text = self._strip_framing(text)

        # Classify
        input_type = self._classify(text)

        context = {
            "input": text,
            "channel": channel,
            "raw": raw,
            "classified_at": datetime.now().isoformat(),
        }

        self._log("inbound", channel, input_type, text[:120])

        return {
            "type": input_type,
            "context": context,
            "reply_channel": channel,
        }

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def send(self, output: Any, channel: str = "default") -> None:
        """
        Format and deliver output to the correct channel.
        """
        formatted = self._format_output(output, channel)
        sink = self._output_sinks.get(channel) or self._output_sinks.get("default")

        if sink:
            try:
                sink(formatted)
            except Exception as e:
                logger.error(f"Error writing to sink '{channel}': {e}")
        else:
            # No sink registered — log it
            logger.info(f"[{channel}] OUTPUT: {formatted[:200]}")

        self._log("outbound", channel, "response", str(formatted)[:120])

    def send_error(self, error_msg: str) -> None:
        """Route an error to the error sink or default output."""
        formatted = f"[ERROR] {error_msg}"
        if self._error_sink:
            try:
                self._error_sink(formatted)
            except Exception:
                pass
        else:
            logger.error(formatted)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(self, text: str) -> str:
        """
        Classify input text into a type label for the planner.
        Uses keyword rules. Replace with embedding-based classification
        when the RAG/embedding layer is available.
        """
        if not text.strip():
            return "idle"

        text_lower = text.lower()
        scores: dict[str, int] = {}

        for keywords, input_type in INPUT_TYPE_RULES:
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > 0:
                scores[input_type] = scores.get(input_type, 0) + count

        if not scores:
            return "unknown"

        return max(scores, key=lambda t: scores[t])

    def _strip_framing(self, text: str) -> str:
        """
        Strip external identity and framing from inbound text.
        Removes things like "As an AI..." preambles that come
        from proxied model responses being fed back in.
        """
        framing_prefixes = [
            "as an ai language model,",
            "as an ai,",
            "as a language model,",
            "certainly! ",
            "of course! ",
            "sure! ",
            "great question! ",
            "i'd be happy to help! ",
        ]
        lower = text.lower().strip()
        for prefix in framing_prefixes:
            if lower.startswith(prefix):
                text = text[len(prefix):].strip()
                logger.debug(f"Stripped external framing prefix: '{prefix}'")
                break
        return text

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _format_output(self, output: Any, channel: str) -> str:
        """
        Format outbound content for the target channel.
        Different channels may want different formatting.
        """
        text = str(output) if not isinstance(output, str) else output

        if channel == "api":
            # API responses — clean, no extra whitespace
            return text.strip()
        elif channel == "user":
            # User-facing — preserve natural formatting
            return text
        elif channel == "internal":
            # Internal messages — plain, no formatting
            return text.strip()
        else:
            return text

    def _to_text(self, raw: Any) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            return raw.get("text") or raw.get("content") or raw.get("message") or str(raw)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, direction: str, channel: str, msg_type: str, preview: str) -> None:
        entry = {
            "direction": direction,
            "channel": channel,
            "type": msg_type,
            "preview": preview,
            "at": datetime.now().isoformat(),
        }
        self._message_log.append(entry)
        # Keep log bounded
        if len(self._message_log) > 500:
            self._message_log = self._message_log[-500:]
        logger.debug(f"[{direction}][{channel}] {msg_type}: {preview[:80]}")

    def traffic_report(self) -> dict:
        """Summary of traffic since startup."""
        inbound = [e for e in self._message_log if e["direction"] == "inbound"]
        outbound = [e for e in self._message_log if e["direction"] == "outbound"]
        return {
            "total_inbound": len(inbound),
            "total_outbound": len(outbound),
            "channels_seen": list({e["channel"] for e in self._message_log}),
            "input_types_seen": list({e["type"] for e in inbound}),
        }
