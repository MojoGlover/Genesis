"""
agent/modules/__init__.py — Infrastructure module client bundle.

All module clients initialized once at boot and passed to graph nodes.
Every client is silent-fail — a module being down never crashes the agent.

Usage:
    from agent.modules import init_modules
    mods = init_modules(config, agent_id, data_dir=data_dir)

    mods.obs.beat(status="ok")
    mods.ledger.record(resource="llm", units=100, cost_usd=0.002)
    response = mods.gateway.chat(messages)
    allowed  = mods.policy.allow(action="tool_call", resource="shell")
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent.modules.obs            import ObsClient
from agent.modules.ledger         import LedgerClient
from agent.modules.gateway        import GatewayClient
from agent.modules.policy         import PolicyClient
from agent.modules.comms          import CommsClient
from agent.modules.registry_client import RegistryClient
from agent.modules.mind_state     import MindStateClient
from agent.modules.scheduler      import SchedulerClient
from agent.modules.tool_bus       import ToolBusClient
from agent.modules.rag            import RAGClient
from agent.modules.grid           import GridResolver
from agent.modules.evidence       import EvidenceLedger
from agent.modules.hardening_eval import HardeningEvalClient


@dataclass
class Modules:
    obs:       ObsClient
    ledger:    LedgerClient
    gateway:   GatewayClient
    policy:    PolicyClient
    comms:     CommsClient
    registry:  RegistryClient
    mind_state: MindStateClient
    scheduler: SchedulerClient
    tool_bus:  ToolBusClient
    rag:       RAGClient
    grid:      GridResolver
    evidence:  EvidenceLedger
    hardening: HardeningEvalClient

    def summary(self) -> str:
        enabled = []
        if self.obs.enabled:       enabled.append("obs")
        if self.ledger.enabled:    enabled.append("ledger")
        if self.gateway.enabled:   enabled.append("gateway")
        if self.policy.enabled:    enabled.append("policy")
        if self.comms.enabled:     enabled.append("comms")
        if self.registry.enabled:  enabled.append("registry")
        if self.mind_state.enabled: enabled.append("mind_state")
        if self.scheduler.enabled: enabled.append("scheduler")
        if self.tool_bus.enabled:  enabled.append("tool_bus")
        if self.rag.enabled:       enabled.append("rag")
        if self.hardening.enabled: enabled.append("hardening")
        # grid and evidence are always available — no enabled flag
        return f"enabled=[{', '.join(enabled)}]"


def init_modules(config: dict, agent_id: str, data_dir: Path | None = None) -> Modules:
    """Build all module clients from config. Called once at boot."""
    base    = config.get("modules", {}).get("base_url", "http://127.0.0.1")
    mods_cfg = config.get("modules", {})
    # PlugOps base URL — canonical source is plugops.url, with fallback to modules.plugops_url
    # for any legacy config that set it there (e.g. mind_state.plugops_url).
    _plugops_url = (
        config.get("plugops", {}).get("url")
        or mods_cfg.get("plugops_url")
        or "https://plugzero-581737577470.us-central1.run.app"
    )

    def url(name: str, default_port: int) -> str:
        port = mods_cfg.get(name, {}).get("port", default_port)
        return f"{base}:{port}"

    def enabled(name: str, default: bool = True) -> bool:
        return mods_cfg.get(name, {}).get("enabled", default)

    gateway = GatewayClient(agent_id, url("model_gateway", 9109),
                             model=config.get("model", {}).get("primary", ""),
                             enabled=enabled("model_gateway"),
                             fallback_ollama=config.get("tools", {}).get("ollama_api", "") or "http://localhost:11434",
                             fallback_model=config.get("model", {}).get("fallback", ""),
                             cloud_fallback_model=config.get("model", {}).get("cloud_fallback", ""),
                             cloud_provider=config.get("model", {}).get("provider", "ollama"),
                             cloud_model=config.get("model", {}).get("cloud_model", ""),
                             # TASK_OLLAMA_URL/MODEL env vars override config — set per-plug
                             # in systemd EnvironmentFile for portability (RunPod, plugwan, etc.)
                             task_ollama=(os.environ.get("TASK_OLLAMA_URL")
                                          or config.get("model", {}).get("task_ollama", "")),
                             task_model=(os.environ.get("TASK_OLLAMA_MODEL")
                                         or config.get("model", {}).get("task_model", "")),
                             model_map=config.get("models", {}))

    hardening_cfg = config.get("hardening", {})
    hardening = HardeningEvalClient(
        agent_id       = agent_id,
        data_dir       = data_dir or Path(f"~/.{agent_id}").expanduser(),
        gateway        = gateway,
        plugops_url    = _plugops_url,
        enabled        = hardening_cfg.get("enabled", True),
        autonomy_level = hardening_cfg.get("autonomy_level", "supervised"),
    )

    return Modules(
        obs        = ObsClient(agent_id, url("observability", 9108),
                               enabled=enabled("observability")),
        ledger     = LedgerClient(agent_id, url("ledger", 9106),
                                  enabled=enabled("ledger")),
        gateway    = gateway,
        policy     = PolicyClient(agent_id, url("policy_gate", 9104),
                                  enabled=enabled("policy_gate")),
        comms      = CommsClient(agent_id, url("communication", 9100),
                                 enabled=enabled("communication")),
        registry   = RegistryClient(agent_id, url("registry", 9101),
                                    enabled=enabled("registry")),
        mind_state = MindStateClient(agent_id, url("mind_state", 9102),
                                     enabled=enabled("mind_state"),
                                     plugops_url=mods_cfg.get("plugops_url", "")),
        scheduler  = SchedulerClient(agent_id, url("scheduler", 9107),
                                     enabled=enabled("scheduler", False)),
        tool_bus   = ToolBusClient(agent_id, url("tool_bus", 9105),
                                   enabled=enabled("tool_bus")),
        rag        = RAGClient(data_dir or Path(f"~/.{agent_id}").expanduser(),
                               agent_id=agent_id,
                               enabled=enabled("rag", True)),
        grid       = GridResolver(plugops_base=_plugops_url),
        evidence   = EvidenceLedger(data_dir or Path(f"~/.{agent_id}").expanduser()),
        hardening  = hardening,
    )
