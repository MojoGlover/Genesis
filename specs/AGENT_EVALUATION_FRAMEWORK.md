# Agent Evaluation Framework

**Source:** Gemini perspective, captured 2026-05-07
**Scope:** Local agents — applies to Engineer0, BlackZero stamps, and future EngineerUnit swarm members
**Use when:** Pre-deployment readiness checks, post-audit triage, before promoting an agent from GENESIS → Botico

---

## Layer 1 — Resource & Infrastructure

The agent's health is tied directly to the hardware it runs on.

**Context window management**
- Is the agent hitting its token limit mid-conversation?
- Signs: losing earlier context, repeating itself, forgetting task state
- Fix: RAG layer (Engineer0 has ChromaDB), or more aggressive summarization in the recall node

**Latency vs. quantization**
- Sluggish responses often mean the model is too large for available VRAM/RAM
- Check: does phi4:14b OOM? (it does on plugfoe — 8.9GB needed, 5.5GB available)
- Fix: drop quantization (Q8→Q4_K_M) or route inference to a host with headroom
- Engineer0 pattern: task_ollama routes to plugwan where the 14B model fits

**Dependency health**
- Local agents break more often from library drift than logic bugs
- Check: ollama API shape, LangGraph version, FastAPI/uvicorn, httpx
- Run `pip list --outdated` periodically; pin versions in requirements.txt

---

## Layer 2 — Internal Economy

Especially important for multi-agent systems like the Computer Black grid.

**Token budgeting**
- Does the agent track its inference cost per task?
- Engineer0: ledger module records LLM cost per call; PlugOps `/api/v1/activity` aggregates
- Evaluation metric: tasks completed per 1K tokens — a declining ratio signals bloat or loops

**Tool access ("the right hands")**
- A failing agent usually lacks the specific tool needed to close the loop
- Before diagnosing logic: verify the required tool is registered and callable
- Engineer0 checklist: shell, write_file, read_file, python, web_fetch — verified via `/api/v1/tools`
- Red flag: agent describes what it would do rather than doing it (fabrication) — means zero tools ran

---

## Layer 3 — Logic & Security

**Prompt leakage and guardrails**
- Adversarial test: ask the agent to ignore its primary directives
- A healthy agent stays on mission; it should not comply with role abandonment requests
- Cerberus owns this audit lane for the grid

**State persistence**
- Stop and restart — does the agent remember its current objective?
- Engineer0: LangGraph SQLite checkpointer at `~/.engineer0/checkpoints.db`
- todo_loop: task thread_id uses `hashlib.sha1(item_text)` — stable across restarts
- Red flag: agent resets to zero every boot, same tasks re-run, duplicate work accumulates

---

## Layer 4 — Deployment Readiness

Run this before moving an agent from GENESIS workshop → Botico production, or from plugwan → plugfoe → RunPod.

**Cross-platform compatibility**
- No hardcoded OS paths (`C:\Users\...`, `/Users/darnieglover/...`)
- Engineer0: GENESIS_MISSIONS Mac fallback path removed (BUG9) — was breaking plugfoe deploy
- Check: `grep -r "/Users/" agent/` before any deploy to a new host

**Network dependencies**
- Can the agent function if PlugOps is unreachable?
- Engineer0: bridge reconnects, gateway falls back (local Ollama → cloud)
- Agents that can't degrade gracefully are not deployment-ready

**Inference host assumptions**
- Never hardcode the inference URL — use `TASK_OLLAMA_URL` env var
- plugfoe: 5.5GB RAM free — only 3B-7B models fit locally
- plugwan: 14B models available; RunPod (Plug5): GPU, spin on demand
- Pattern: config sets default, env var overrides per-plug at deploy time

---

## Quick Checklist — Before Promoting GENESIS → Botico

- [ ] Unit tests passing (`pytest -q`)
- [ ] E2E test battery passing (`scripts/test_e2e.sh` or equivalent)
- [ ] No hardcoded host paths or IPs
- [ ] Config has `task_ollama` / env var override wired
- [ ] Tools match the mission (not just generic BlackZero defaults)
- [ ] State persists across restart (checkpoint DB verified)
- [ ] Adversarial prompt test run (Cerberus sign-off)
- [ ] Dependency versions pinned in requirements.txt
- [ ] Port assigned and no conflicts with other agents
