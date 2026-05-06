"""
main_tool.py — ToolZero boot sequence.

Starts:
  1. PlugOps bridge (registration, heartbeat, tool_request routing)
  2. FastAPI server (/health, /execute)

No LLM. No graph. No mission. Just tools.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn
import yaml

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ── Tool request handler ──────────────────────────────────────────────────────

async def handle_tool_request(msg: dict) -> dict:
    """Called by bridge when Operator routes a tool_request here."""
    from agent.tools.registry import execute
    tool_name = msg.get("tool", "")
    params    = msg.get("params", {})
    try:
        result = execute(tool_name, params)
        return {"result": result, "error": None}
    except Exception as e:
        return {"result": "", "error": str(e)}


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    cfg = load_config()
    setup_logging(cfg.get("logging", {}).get("level", "INFO"))

    identity = cfg.get("identity", {})
    agent_id   = identity.get("alias",       "toolzero")
    agent_name = identity.get("designation", "ToolZero")
    agent_role = identity.get("role",        "Tool agent")
    port       = cfg.get("server", {}).get("port", 5099)
    capabilities = cfg.get("capabilities", ["tool_execution"])

    plugops_url = os.environ.get(
        "PLUGOPS_URL",
        cfg.get("plugops", {}).get("url", f"ws://localhost:9000/ws/{agent_id}")
    )

    logger.info = logging.getLogger(__name__).info
    log = logging.getLogger(__name__)
    log.info(f"{'━'*40}")
    log.info(f"  {agent_name} ({agent_id})")
    log.info(f"  Role: {agent_role}")
    log.info(f"  Port: {port}")
    log.info(f"  PlugOps: {plugops_url}")
    log.info(f"{'━'*40}")

    from agent.plugops.bridge import ToolBridge
    bridge = ToolBridge(
        url              = plugops_url,
        agent_id         = agent_id,
        agent_name       = agent_name,
        agent_role       = agent_role,
        capabilities     = capabilities,
        on_tool_request  = handle_tool_request,
    )

    from agent.api.server import app
    server_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(server_config)

    await asyncio.gather(
        bridge.connect(),
        server.serve(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown.")
