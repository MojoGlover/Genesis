"""
main_agent.py — BlackZero agent entry point.

Boot sequence:
  1. Load config.yaml
  2. Load mission
  3. Build system prompt
  4. Run bootstrap check
  5. Build LangGraph
  6. Connect to PlugOps (runs forever)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────

BLACKZERO_DIR = Path(__file__).parent
MISSIONS_DIR  = BLACKZERO_DIR / "missions"

# Also check GENESIS/missions as fallback
GENESIS_MISSIONS = Path("/Users/darnieglover/ai/cmptrblk/GENESIS/missions")


def find_missions_dir(agent_id: str) -> Path:
    """Find the missions directory that has our mission file."""
    name = f"{agent_id.upper()}.mission.txt"
    if (MISSIONS_DIR / name).exists():
        return MISSIONS_DIR
    if (GENESIS_MISSIONS / name).exists():
        return GENESIS_MISSIONS
    # Return local dir — MissionLoader will give a clear error
    return MISSIONS_DIR


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    from agent.core.mission import MissionLoader, MissionMissingError
    from agent.core.graph import build_graph
    from agent.core.state import AgentIdentity
    from agent.plugops.bridge import PlugOpsBridge
    from agent.plugops.handler import MessageHandler

    # 1. Config
    config_path = BLACKZERO_DIR / "config.yaml"
    if not config_path.exists():
        logger.error(f"config.yaml not found at {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Resolve agent_id: env var wins (useful for multi-agent containers),
    # otherwise fall back to identity.alias in config, then "agent".
    # Never default to "blackzero" — that's the template name, not the agent's name.
    agent_id   = os.environ.get("AGENT_ID") or config.get("identity", {}).get("alias", "agent")
    agent_name = config.get("identity", {}).get("designation", agent_id)
    data_dir   = Path(config.get("data_dir", f"~/.{agent_id}")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting {agent_name} (id={agent_id})")
    logger.info(f"Data dir: {data_dir}")

    # 2. Mission
    missions_dir = find_missions_dir(agent_id)
    loader = MissionLoader(missions_dir)

    try:
        mission = loader.load(agent_id)
    except MissionMissingError as e:
        logger.error(f"[mission] FATAL: {e}")
        sys.exit(1)

    identity = AgentIdentity(
        name=agent_name,
        alias=config.get("identity", {}).get("alias", agent_id),
        role=config.get("identity", {}).get("role", "Agent"),
        owner=config.get("identity", {}).get("owner", "Computer Black"),
        model=config.get("models", {}).get("chat", f"{agent_id}:latest"),
        capabilities=config.get("modules", {}).get("plugops_bridge", {}).get("capabilities", []),
    )

    # 3. System prompt
    system_prompt = loader.build_system_prompt(mission, identity)

    # 4. Build graph (also returns llm for bootstrap)
    logger.info("[graph] Building LangGraph...")
    graph, llm = build_graph(config, system_prompt, data_dir)

    # 5. Bootstrap check
    verified = loader.bootstrap_check(llm, system_prompt, agent_name)
    loader.save_bootstrap_result(data_dir, verified, agent_name)
    if verified:
        logger.info("[bootstrap] PASS — mission acknowledged")
    else:
        logger.warning("[bootstrap] WARN — unexpected bootstrap response (continuing anyway)")

    # 6. PlugOps bridge — env var → config → fallback (same pattern as BlackZero template)
    plugops_url = (
        os.environ.get("PLUGOPS_URL")
        or config.get("plugops", {}).get("url", "")
        or f"ws://localhost:9000/ws/{agent_id}"
    )

    bridge = PlugOpsBridge(
        url=plugops_url,
        agent_id=agent_id,
        agent_name=agent_name,
        capabilities=identity.capabilities,
        on_message_callback=None,  # set below
    )

    handler = MessageHandler(
        graph=graph,
        bridge=bridge,
        agent_name=agent_name,
        mission_context=system_prompt,
    )

    bridge.on_message_callback = handler.handle

    logger.info(f"[bridge] Connecting to PlugOps at {plugops_url}")

    # 7. Initialize HTTP API + run bridge and API server concurrently
    from agent.api.server import app as api_app, init as init_api
    import uvicorn

    api_port = int(config.get("api", {}).get("port", 5001))
    init_api(agent_id, graph, system_prompt, data_dir)

    api_config = uvicorn.Config(api_app, host="0.0.0.0", port=api_port, log_level="warning")
    api_server = uvicorn.Server(api_config)

    logger.info(f"[api] HTTP server starting on port {api_port}")
    logger.info(f"{agent_name} ready.")

    await asyncio.gather(
        bridge.connect(),
        api_server.serve(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
