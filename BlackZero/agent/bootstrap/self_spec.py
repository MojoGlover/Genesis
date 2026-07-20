"""
agent/bootstrap/self_spec.py — First-boot self-spec: gap detection + personality draft.

Runs once when FIRST_BOOT=true (wired into main.py's boot sequence, step 3b —
see agent/core/startup.py). Reads this agent's own mission file, diffs what
the mission implies it needs against what agent/modules/tool_bus.py's
ToolBusClient can actually reach, files a PlugOps capability_request for
every gap, and drafts identity/personality.yaml from the mission text so a
newly stamped agent doesn't start with the template's placeholder strings.

Mission-to-capability inference intentionally mirrors PlugOps's
POST /api/agents/bootstrap (plugops/api/bootstrap.py, cmptrblk/PlugOps repo)
rule-for-rule. Duplicated rather than imported: GENESIS agents are
self-contained and never import across repos at runtime (GENESIS/CLAUDE.md
"Agent Architecture: Self-Contained Modules"). If you tune one rule table,
tune the other.

Caveat (documented per "no silent placeholders" — this isn't hidden, it's
loud): agent/modules/tool_bus.py's ToolBusClient talks to the port-9105
module daemon, which is part of the 9100s stack retired 2026-06-11 (see
cmptrblk/CLAUDE.md). Until that daemon exists again, list_tools() returns
[] and every inferred capability comes back as a "gap" — this is a coarse,
honest signal ("nothing on the tool bus advertises this name"), not a claim
that the agent has zero working tools. Every stamped agent already ships
the generic dispatch table in agent/tools/registry.py (shell, read_file,
write_file, web_fetch, web_search, ask_agent, send_to_agent, ...) regardless
of what this module reports.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0

# ── Mission → capability inference rules ─────────────────────────────────────
# Kept in lockstep with PlugOps's plugops/api/bootstrap.py::_INFERENCE_RULES.
_INFERENCE_RULES: list[dict[str, Any]] = [
    {
        "name": "routing",
        "phrases": ["routes to", "hands off", "ask_agent", "route to", "hand off"],
        "tools": ["send_to_agent", "list_agents"],
    },
    {
        "name": "web_search",
        "phrases": ["search", "web", "find information"],
        "tools": ["web_search", "web_fetch"],
    },
    {
        "name": "memory",
        "phrases": ["remember", "past conversations", "memory", "what he said"],
        "tools": [],
        "rag": True,
    },
    {
        "name": "files",
        "phrases": ["file", "read", "write", "document"],
        "tools": ["file_read", "file_write"],
    },
    {
        "name": "shell",
        "phrases": ["shell", "execute", "run command"],
        "tools": ["shell"],
    },
    {
        "name": "ledger",
        "phrases": ["budget", "spend", "cost", "accountant"],
        "tools": ["ledger_query"],
    },
    {
        "name": "telegram",
        "phrases": ["telegram", "notify", "message darnie"],
        "tools": ["telegram_send"],
    },
    {
        "name": "calendar",
        "phrases": ["calendar", "remind", "schedule"],
        "tools": ["calendar"],
    },
    {
        "name": "git",
        "phrases": ["git", "commit", "push", "repo"],
        "tools": ["git_ops"],
    },
    {
        "name": "code",
        "phrases": ["code", "python", "script"],
        "tools": ["python_repl"],
    },
]


def _infer_capabilities(mission_text: str) -> dict[str, Any]:
    """Pure function — same shape as PlugOps's infer_tools_from_mission()."""
    text_lower = mission_text.lower()
    tools: list[str] = []
    rag_needed = False
    inferred_from: dict[str, str] = {}

    for rule in _INFERENCE_RULES:
        matched = next((p for p in rule["phrases"] if p in text_lower), None)
        if not matched:
            continue
        for tool in rule.get("tools", []):
            if tool not in tools:
                tools.append(tool)
            inferred_from.setdefault(tool, f"matched '{matched}'")
        if rule.get("rag"):
            rag_needed = True
            inferred_from.setdefault("rag", f"matched '{matched}'")

    return {"tools": tools, "rag_needed": rag_needed, "inferred_from": inferred_from}


def _registered_tool_names(tool_bus: Any) -> set[str]:
    """Best-effort — a down/disabled tool_bus means treat everything as
    missing rather than crash first boot over it (same silent-fail contract
    as every other module client in agent/modules/)."""
    try:
        listed = tool_bus.list_tools()
    except Exception as e:
        logger.warning(f"[self_spec] tool_bus.list_tools() failed: {e}")
        return set()
    names: set[str] = set()
    for entry in listed or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if name:
            names.add(name)
    return names


def _file_capability_request(
    plugops_url: str, agent_id: str, tool_name: str, reason: str
) -> dict[str, Any]:
    """POST to PlugOps /api/agents/capability_request. Direct HTTP call —
    same pattern as agent/tools/messaging.py and agent/plugops/bridge.py,
    both of which call PlugOps over plain httpx rather than any stdio
    channel. Never raises: a failed filing is logged and reported back in
    the gap's request record, not fatal to boot."""
    base = plugops_url.rstrip("/")
    try:
        r = httpx.post(
            f"{base}/api/agents/capability_request",
            json={
                "agent_id": agent_id,
                "tool_name": tool_name,
                "reason": reason,
                "priority": "high",
            },
            timeout=_DEFAULT_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
        logger.warning(
            f"[self_spec] capability_request for '{tool_name}' returned {r.status_code}"
        )
        return {"request_id": None, "status": "failed", "http_status": r.status_code}
    except Exception as e:
        logger.warning(f"[self_spec] capability_request for '{tool_name}' failed: {e}")
        return {"request_id": None, "status": "failed", "error": str(e)}


# ── Personality guided interview ──────────────────────────────────────────────
# Questions answered directly from mission text — no human needed for the
# obvious cases. A blank/empty result for any field just means the mission
# didn't say; nothing here fabricates an answer.

_TONE_WORDS = [
    "warm", "direct", "cheerful", "formal", "professional", "playful", "blunt",
    "concise", "empathetic", "analytical", "methodical", "curious", "decisive",
    "honest", "genuine",
]

_PERSONALITY_HEADING_RE = re.compile(r"^[ \t]*PERSONALITY\b.*$", re.IGNORECASE | re.MULTILINE)
_AUTHORITY_RE = re.compile(r"\banswers? to ([A-Z][\w .]+?)\.", re.IGNORECASE)
_ONLY_RE = re.compile(r"\bOnly ([A-Z][\w]+)\b")
_ROUTING_RE = re.compile(r"→\s*([A-Z][\w ]*?)(?:\.|\n|$)")


def _personality_section(mission_text: str) -> str:
    """Text from the first 'PERSONALITY' heading to the end, if present —
    narrows tone-word extraction to where the mission actually describes
    personality instead of the whole document. Falls back to full text."""
    m = _PERSONALITY_HEADING_RE.search(mission_text)
    return mission_text[m.start():] if m else mission_text


def _draft_personality(
    mission_text: str, known_agent_names: list[str] | None = None
) -> dict[str, Any]:
    section_lower = _personality_section(mission_text).lower()

    tone = sorted({w for w in _TONE_WORDS if w in section_lower})

    m = _AUTHORITY_RE.search(mission_text)
    reports_to = m.group(1).strip() if m else ""
    if not reports_to:
        m2 = _ONLY_RE.search(mission_text)
        if m2:
            reports_to = m2.group(1).strip()

    routing_targets = sorted({t.strip() for t in _ROUTING_RE.findall(mission_text) if t.strip()})
    if not routing_targets and known_agent_names:
        text_lower = mission_text.lower()
        routing_targets = sorted({n for n in known_agent_names if n.lower() in text_lower})

    text_lower = mission_text.lower()
    profanity_ok = any(kw in text_lower for kw in ("profanity", "no filter", "direct"))
    brief = "brief" in text_lower or "concise" in text_lower or "short" in text_lower

    return {
        "tone": ", ".join(tone),
        "communication_style": "brief and precise" if brief else "",
        "traits": tone,
        "boundaries": [],
        "response_defaults": {
            "max_verbosity": "low" if brief else "",
            "preferred_format": "prose",
        },
        "audience": reports_to,
        "authority": reports_to,
        "routes_to": routing_targets,
        "profanity_ok": profanity_ok,
    }


def _write_personality_yaml(identity_dir: Path, draft: dict[str, Any]) -> bool:
    identity_dir.mkdir(parents=True, exist_ok=True)
    out_path = identity_dir / "personality.yaml"
    try:
        out_path.write_text(yaml.dump(draft, sort_keys=False, default_flow_style=False))
        logger.info(f"[self_spec] wrote {out_path}")
        return True
    except Exception as e:
        logger.error(f"[self_spec] failed to write {out_path}: {e}")
        return False


# ── Entry point ────────────────────────────────────────────────────────────

def run_self_spec(
    mission_path: Path,
    tool_bus: Any,
    plugops_url: str,
    agent_id: str,
    identity_dir: Path | None = None,
) -> dict[str, Any]:
    """
    1. Read mission file
    2. Check what tools are actually registered in tool_bus
    3. Identify gaps: tools implied by mission but missing from tool_bus
    4. For each gap: POST to PlugOps /api/agents/capability_request
    5. Generate and write identity/personality.yaml via guided questions
    6. Return: {"gaps_found": [...], "requests_filed": [...], "personality_written": bool}

    Best-effort throughout — a missing mission file, an unreachable tool_bus,
    or a failed PlugOps POST are all logged and reflected in the return value,
    never raised. First boot must not crash over this.
    """
    mission_path = Path(mission_path)
    if not mission_path.exists():
        logger.error(f"[self_spec] mission file not found: {mission_path}")
        return {"gaps_found": [], "requests_filed": [], "personality_written": False}

    mission_text = mission_path.read_text(encoding="utf-8", errors="replace")

    inference = _infer_capabilities(mission_text)
    registered = _registered_tool_names(tool_bus)
    gaps = [t for t in inference["tools"] if t not in registered]

    requests_filed: list[dict[str, Any]] = []
    for tool_name in gaps:
        reason = (
            f"Mission implies '{tool_name}' "
            f"({inference['inferred_from'].get(tool_name, 'inferred from mission text')}) "
            f"but it is not registered on the tool bus."
        )
        result = _file_capability_request(plugops_url, agent_id, tool_name, reason)
        requests_filed.append({"tool_name": tool_name, **result})

    identity_dir = identity_dir or (mission_path.parent.parent / "identity")
    draft = _draft_personality(mission_text)
    personality_written = _write_personality_yaml(identity_dir, draft)

    logger.info(
        f"[self_spec] {agent_id}: gaps={gaps} requests_filed={len(requests_filed)} "
        f"personality_written={personality_written}"
    )

    return {
        "gaps_found": gaps,
        "requests_filed": requests_filed,
        "personality_written": personality_written,
    }
