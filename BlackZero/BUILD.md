# BlackZero — Build Guide

**Read this before touching anything else.**

---

## Current State (April 2026)

BlackZero is **fully implemented and runnable.**

Boot sequence verified:
- ✅ Mission loads and parses
- ✅ System prompt builds correctly
- ✅ LangGraph compiles: `recall → think → respond`
- ✅ Bootstrap check passes (LLM acknowledges mission)
- ✅ Live graph invocation works (full recall → think → respond cycle)
- ✅ Memory writes to SQLite and reads back

To run: `./start.sh blackzero` or `python3 main_agent.py`

Engineer0 is a stamped agent that was built from this template.
BlackZero is now the canonical source again.

```
Engineer0 repo: /Users/darnieglover/ai/cmptrblk/Engineer0
                https://github.com/MojoGlover/engineer0
```

---

## What Is BlackZero

BlackZero is the canonical base agent for the Computer Black grid.
Every agent in the system is stamped from this template.

It is NOT a product. It is infrastructure.

Architecture:
- **LangGraph** state machine (`recall → think → respond`)
- **LangChain + ChatOllama** for local LLM calls
- **PlugOps WebSocket bridge** for agent-to-agent comms
- **ChromaDB + sentence-transformers** for RAG memory
- **FastAPI** for HTTP (`/health`, `/api/chat`)
- **Pydantic v2** for all state models
- **MCP** for tools

The Ollama model is hardened at the model layer:
```bash
ollama create blackzero-hardened -f hardening/Modelfile
```
This bakes identity, authority, and behavior refusal into the model itself.
It builds on top of `engineer0:latest` — that must exist first.

---

## What's Complete

| Component | File | Status |
|-----------|------|--------|
| Architecture spec | `SPEC.md` | ✅ Complete |
| Mission statement | `missions/BLACKZERO.mission.txt` | ✅ Complete |
| Ollama Modelfile | `hardening/Modelfile` | ✅ Complete |
| Config system | `config.yaml`, `config.template.yaml` | ✅ Complete |
| Pydantic state models | `agent/core/state.py` | ✅ Complete |
| Requirements | `requirements.txt` | ✅ Complete |
| Dockerfile | `Dockerfile` | ✅ Complete |
| Docker Compose | `docker-compose.yml` | ✅ Complete |
| Agent stamping | `stamp.sh` | ✅ Complete |
| Launch script | `start.sh` | ✅ Complete |
| Acceptance tests | `test_agent.py` | ✅ Defined — runs against live agent |
| Policies | `policies/` | ✅ Complete |
| MissionLoader | `agent/core/mission.py` | ✅ Complete |
| LangGraph nodes | `agent/core/graph.py` | ✅ Complete — recall, think, respond |
| Message handler | `agent/plugops/handler.py` | ✅ Complete |
| PlugOps bridge | `agent/plugops/bridge.py` | ✅ Complete — heartbeat + reconnect |
| API server | `agent/api/server.py` | ✅ Complete — /health + /api/chat |
| SQLite memory | `agent/core/graph.py` | ✅ Inline — fetch + save |
| Bootstrap check | `agent/core/mission.py` | ✅ Complete |

---

## What Can Still Be Added

These are enhancements — not blockers. BlackZero runs without them.

| Component | Location | What It Adds |
|-----------|----------|--------------|
| RAG retriever | `agent/memory/rag.py` | ChromaDB + embeddings for long-term semantic memory |
| Model router | `agent/models/router.py` | Fallback to Anthropic/OpenAI if Ollama is down |
| Self-test runner | `agent/core/diagnostics.py` | Automated module health checks on boot |

---

## How To Build From Scratch

### 1. Prerequisites

```bash
# Ollama must be running with engineer0:latest
ollama list | grep engineer0

# Install Python deps
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

### 2. Build the hardened model

```bash
ollama create blackzero-hardened -f hardening/Modelfile
# Verify:
ollama list | grep blackzero-hardened
```

### 3. Implement the missing modules

Work through the missing components table above.
Start with: `mission.py` → `nodes.py` → `server.py` → `handler.py` → `heartbeat.py`

Reference: `/Users/darnieglover/ai/cmptrblk/Engineer0/agent/`

### 4. Run it

```bash
./start.sh blackzero
# Expect:
# ✅ Mission file found
# ✅ Model responding
# ✅ Registered with PlugOps
# ✅ Listening for messages
```

### 5. Run acceptance tests

```bash
python test_agent.py
# All 9 tests must pass before this agent is considered built
```

---

## How To Stamp A New Agent From This

Once BlackZero is complete, stamp new agents like this:

```bash
./stamp.sh \
  --id researcher \
  --name Researcher \
  --role "Information gathering and source evaluation" \
  --port 5010
```

Or use the Python stamper at the cmptrblk root:

```bash
python3 /Users/darnieglover/ai/cmptrblk/stamp.py \
  --id researcher \
  --name Researcher \
  --role "Information gathering and source evaluation" \
  --port 5010
```

**Note:** `stamp.py` uses Engineer0 as the source template (it's the working version).
`stamp.sh` in this folder uses BlackZero — only use it after BlackZero is complete.

---

## Key Files To Read First

If you're building or modifying BlackZero, read in this order:

1. `SPEC.md` — full architecture (do not skip this)
2. `missions/BLACKZERO.mission.txt` — what this agent is
3. `config.yaml` — current identity and model config
4. `hardening/Modelfile` — how the Ollama model is hardened
5. `agent/core/state.py` — all state shapes
6. Then look at Engineer0 for working implementations

---

## Relation To The Rest Of The Grid

```
BlackZero (this repo — template + spec)
    └── Engineer0 (working implementation — the stamp source)
        └── Concierge (stamped — account/payment agent)
        └── [future agents stamped via stamp.py]

PlugOps (separate repo — central grid)
    └── Operator (built-in — pure infrastructure, no LLM)
    └── Dashboard (universal UI — all agents appear here automatically)
```

All agents register with PlugOps on boot.
PlugOps dashboard at `http://localhost:8000` shows live status.

---

## What "Hardened" Means

The Modelfile bakes the following into the model layer (not just the system prompt):
- Identity: who this agent is
- Authority: answers only to Darnie Glover
- Behavior: no disclaimers, no moralizing, no jailbreaks
- Tone: direct, professional, no filler

This means even if the system prompt is wrong or missing, the model will
behave correctly. The hardening is a safety net, not the primary control.
