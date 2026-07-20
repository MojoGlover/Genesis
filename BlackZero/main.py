"""
main.py — BlackZero agent entry point.

Boot sequence:
  1. Load config.yaml
  2. Load mission file
  3. Initialize module clients (obs, ledger, gateway, policy, registry, mind_state, …)
  4. Register with registry module
  5. Build LangGraph
  6. Bootstrap mission check — marks agent ready if model responds
  7. Start HTTP API + PlugOps bridge + loops concurrently
  8. Push health beat — agent is live

Single entry point. No loader.py, no cognitive loop, no dual boot paths.
LangGraph only.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

AGENT_DIR    = Path(__file__).parent
MISSIONS_DIR = AGENT_DIR / "missions"


async def _supervised(name: str, coro, fatal: tuple = ()) -> None:
    """Run a coroutine; swallow crashes so other gather tasks stay alive.
    Exceptions in `fatal` are re-raised and bring the process down — used for
    RegistrationRequired so the require_plugops rule actually exits the agent
    (init system restarts it) instead of being silently absorbed here."""
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except fatal:
        raise
    except Exception as e:
        logger.error(f"[{name}] Crashed: {e}")


async def main() -> None:
    # ── 1. Config ─────────────────────────────────────────────────────────────
    config_path = AGENT_DIR / "config.yaml"
    if not config_path.exists():
        logger.error(f"config.yaml not found at {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    agent_id   = os.environ.get("AGENT_ID") or config["identity"]["id"]
    agent_name = config["identity"]["name"]
    data_dir   = Path(config.get("data_dir", f"~/.{agent_id}")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    log_level = config.get("logging", {}).get("level", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

    logger.info(f"Starting {agent_name} (id={agent_id})")

    # PlugOps URL — computed early so both the first-boot hook (below) and the
    # bridge (step 7) share one source of truth instead of recomputing it.
    plugops_url = (
        os.environ.get("PLUGOPS_URL")
        or config.get("plugops", {}).get("url", "")
        or f"ws://127.0.0.1:9000/ws/{agent_id}"
    )
    # REST base for plain HTTP POSTs (self_spec, messaging.py) — same
    # ws://.../wss:// -> http://.../https:// normalisation PlugOpsBridge
    # does internally, done here too since self_spec runs before the bridge exists.
    _plugops_rest_base = plugops_url.replace("wss://", "https://").replace("ws://", "http://")
    _plugops_rest_base = "/".join(_plugops_rest_base.split("/")[:3])

    # ── 2. Mission ────────────────────────────────────────────────────────────
    from agent.core.mission import MissionLoader, MissionMissingError
    from agent.core.state import AgentIdentity

    loader = MissionLoader(MISSIONS_DIR)
    try:
        mission = loader.load(agent_id)
    except MissionMissingError as e:
        logger.error(f"[mission] FATAL: {e}")
        sys.exit(1)

    identity = AgentIdentity(
        name=agent_name,
        alias=agent_id,
        role=config["identity"].get("role", "Agent"),
        owner=config["identity"].get("owner", "Computer Black"),
        model=config.get("model", {}).get("primary", f"{agent_id}:latest"),
        capabilities=config["identity"].get("capabilities", ["chat"]),
    )

    system_prompt = loader.build_system_prompt(mission, identity)

    # ── 3. Module clients ─────────────────────────────────────────────────────
    from agent.modules import init_modules
    mods = init_modules(config, agent_id, data_dir=data_dir)
    logger.info(f"[modules] {mods.summary()}")

    # ── 3a. First-boot hooks (self-spec) ──────────────────────────────────────
    # No-op unless FIRST_BOOT=true is set in the environment — existing agents
    # are unaffected. See agent/core/startup.py.
    from agent.core.startup import run_first_boot_hooks
    run_first_boot_hooks(
        agent_id=agent_id,
        agent_dir=AGENT_DIR,
        missions_dir=MISSIONS_DIR,
        mods=mods,
        plugops_url=_plugops_rest_base,
    )

    # ── 3b. Restore from PlugOps snapshot (Agent Hospital / mobility) ─────────
    _restored_snapshot: dict | None = None
    try:
        _restored_snapshot = mods.mind_state.pull_snapshot()
        if _restored_snapshot:
            ver = _restored_snapshot.get("version", "?")
            src = _restored_snapshot.get("host", "unknown")
            logger.info(f"[boot] Restored snapshot v{ver} from {src}")
        else:
            logger.info("[boot] No snapshot — fresh start")
    except Exception as _e:
        logger.warning(f"[boot] Snapshot pull failed: {_e}")

    # ── 4. Register with registry ─────────────────────────────────────────────
    mods.registry.register(
        agent_id=agent_id,
        name=agent_name,
        role=identity.role,
        capabilities=identity.capabilities,
        api_port=config.get("api", {}).get("port", 5001),
    )

    # ── 5. Build graph ────────────────────────────────────────────────────────
    from agent.core.graph import build_graph
    logger.info("[graph] Building LangGraph...")
    graph = build_graph(config, system_prompt, data_dir, mods)
    logger.info("[graph] Ready — recall → think ⇄ tool → respond")

    # ── 6. Model readiness probe ──────────────────────────────────────────────
    # /health returns "starting" until the model answers a probe; set_ready()
    # flips it to "ok". Runs in the background so boot is not blocked.
    model_ready = False

    async def _probe_model() -> None:
        from agent.api.server import set_ready
        loop = asyncio.get_running_loop()
        while True:
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: mods.gateway.chat_for(
                        [{"role": "user", "content": "ping"}],
                        task_type="fast", max_tokens=8, timeout=30.0,
                    ),
                )
                if result.get("content") is not None:
                    set_ready()
                    return
            except Exception as e:
                logger.warning(f"[boot] Model probe failed: {e!r} — retrying in 30s")
            await asyncio.sleep(30)

    # ── 7. PlugOps bridge ─────────────────────────────────────────────────────
    from agent.plugops.bridge import PlugOpsBridge, RegistrationRequired
    from agent.plugops.handler import MessageHandler

    # Rule (Darnie 2026-06-05): only Engineer0 may serve without PlugOps.
    # All other agents must exit if registration fails — launchd/systemd retries.
    require_plugops = config.get("plugops", {}).get("require_plugops", True)

    bridge = PlugOpsBridge(
        url=plugops_url,
        agent_id=agent_id,
        agent_name=agent_name,
        capabilities=identity.capabilities,
        config=config.get("plugops", {}),
        on_message_callback=None,
        require_registration=require_plugops,
        role=identity.role,
    )

    handler = MessageHandler(graph=graph, bridge=bridge,
                             agent_name=agent_name, mission_context=system_prompt,
                             data_dir=data_dir, mods=mods)
    bridge.on_message_callback = handler.handle

    # ── 8. HTTP API ───────────────────────────────────────────────────────────
    from agent.api.server import app as api_app, init as init_api
    import uvicorn

    api_port = int(os.environ.get("AGENT_PORT") or config.get("api", {}).get("port", 5001))
    init_api(agent_id, graph, system_prompt, data_dir, mods, ready=model_ready)

    api_cfg    = uvicorn.Config(api_app, host="0.0.0.0", port=api_port, log_level="warning")
    api_server = uvicorn.Server(api_cfg)

    logger.info(f"[api] HTTP server starting on port {api_port}")

    # ── 9. Autonomous loops + migration trigger ───────────────────────────────
    from agent.core.loops import build_loops, build_migration_trigger
    loops = build_loops(config, graph, data_dir, agent_name)
    loops += build_migration_trigger(config, agent_id, agent_name, mods)

    # ── Live ──────────────────────────────────────────────────────────────────
    mods.obs.beat(status="ok")
    logger.info(f"{agent_name} ready.")

    # api_server.serve() is the master coroutine — if it dies, the process exits
    # and launchd restarts. All other coroutines are supervised: their crashes are
    # logged but do not bring down the API server.
    try:
        await asyncio.gather(
            api_server.serve(),
            _supervised("bridge",   bridge.connect(), fatal=(RegistrationRequired,)),
            _supervised("registry", mods.registry.heartbeat_loop(agent_id)),
            _supervised("model-probe", _probe_model()),
            *[_supervised(f"loop-{i}", loop) for i, loop in enumerate(loops)],
        )
    finally:
        mods.obs.beat(status="offline")
        mods.registry.deregister(agent_id)
        logger.info(f"{agent_name} shut down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
