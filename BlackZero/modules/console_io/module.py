"""
console_io — stdin/stdout interface for the cognitive loop.

Provides:
    - Output sinks that write to stdout (user + default channels)
    - Error sink to stderr
    - Input feed that reads stdin in a background thread and pushes
      lines into the Router via router.ingest()

Agent alias is read from config.identity.alias (falls back to "Agent").

Returns:
    {
        "sinks":      {"user": ..., "default": ...},
        "error_sink": ...,
        "input_feed": [attach_fn],
    }
"""
from __future__ import annotations

import sys
import threading
import logging

logger = logging.getLogger(__name__)


def _make_user_sink(alias: str) -> callable:
    def sink(output: str) -> None:
        if output and output.strip():
            print(f"\n{alias}> {output}\n", flush=True)
    return sink


def _make_error_sink() -> callable:
    def sink(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)
    return sink


def _make_input_feeder() -> callable:
    def attach(router) -> None:
        def _read_loop():
            try:
                while True:
                    try:
                        line = input("You> ")
                    except EOFError:
                        logger.info("stdin closed (EOF). Stopping input feed.")
                        break
                    if line.strip():
                        router.ingest(line.strip(), channel="user")
            except Exception as e:
                logger.error(f"Console input feed error: {e}")

        t = threading.Thread(target=_read_loop, daemon=True, name="console_input")
        t.start()
        logger.info("Console input feed started.")

    return attach


def setup(config: dict) -> dict:
    """Module entry point. Called by the loader."""
    identity = config.get("identity", {})
    alias    = identity.get("alias") or identity.get("designation", "Agent")

    user_sink = _make_user_sink(alias)

    return {
        "sinks": {
            "user":    user_sink,
            "default": user_sink,
        },
        "error_sink": _make_error_sink(),
        "input_feed": [_make_input_feeder()],
    }
