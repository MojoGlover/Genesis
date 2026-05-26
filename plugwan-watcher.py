#!/usr/bin/env python3
"""
plugwan-watcher.py — Runs on plugwan (Mac). Polls PlugOps for pending agent
migrations targeting plugwan, then starts the agent via launchctl.

Managed by launchd: ~/Library/LaunchAgents/com.cmptrblk.plugwan-watcher.plist

Polls: GET /api/v1/agents/migration/pending?host=plugwan every 30s
Action: launchctl start com.cmptrblk.{agent_id}

The migration lock was set by the agent on plugfoe before it shut down.
When the new instance on plugwan registers with the Operator, the lock clears
and the plugfoe watchdog terminates the old instance.
"""
import json
import logging
import os
import socket
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

# Set a global socket timeout so DNS + connection never hang indefinitely
socket.setdefaulttimeout(15)

# macOS system Python may lack CA certs — use a permissive context for PlugOps (internal, trusted)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [plugwan-watcher] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PLUGOPS_URL  = os.environ.get("PLUGOPS_URL", "https://plugzero-581737577470.us-central1.run.app")
POLL_INTERVAL = 30   # seconds
HOST_NAME    = "plugwan"

# Agents this Mac knows how to start (launchd service labels)
# Maps agent_id → launchd label
_SERVICE_MAP: dict[str, str] = {
    "blackzero":        "com.cmptrblk.blackzero",
    "researcher":       "com.cmptrblk.researcher",
    "process_architect": "com.cmptrblk.process_architect",
    "teacher":          "com.cmptrblk.teacher",
    "madjanet":         "com.cmptrblk.madjanet",
    "engineer0":        "com.cmptrblk.engineer0",
}

_started: set[str] = set()   # track what we started this session


def fetch_pending() -> list[dict]:
    url = f"{PLUGOPS_URL}/api/v1/agents/migration/pending?host={HOST_NAME}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            data = json.loads(resp.read().decode())
            return data.get("pending", [])
    except Exception as e:
        logger.warning(f"Poll failed: {e}")
        return []


def start_agent(agent_id: str) -> bool:
    label = _SERVICE_MAP.get(agent_id)
    if not label:
        logger.warning(f"No launchd label for {agent_id} — cannot start")
        return False

    try:
        result = subprocess.run(
            ["launchctl", "start", label],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info(f"Started {agent_id} via launchctl ({label})")
            return True
        else:
            logger.warning(f"launchctl start {label} failed: {result.stderr.strip()}")
            return False
    except Exception as e:
        logger.error(f"Failed to start {agent_id}: {e}")
        return False


def main() -> None:
    logger.info(f"plugwan-watcher started — polling {PLUGOPS_URL} every {POLL_INTERVAL}s")

    while True:
        pending = fetch_pending()
        if pending:
            logger.info(f"{len(pending)} pending migration(s) for {HOST_NAME}")
        for migration in pending:
            agent_id = migration.get("agent_id", "")
            if not agent_id:
                continue
            if agent_id in _started:
                logger.debug(f"{agent_id} already started this session — skipping")
                continue
            logger.info(
                f"Migration detected: {agent_id} "
                f"({migration.get('source_node')} → {HOST_NAME})"
            )
            if start_agent(agent_id):
                _started.add(agent_id)

        # Clear started set when no migrations pending (agents registered, locks cleared)
        if not pending and _started:
            logger.info(f"No pending migrations — clearing started set: {_started}")
            _started.clear()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
