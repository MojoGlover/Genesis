# GENESIS

**GENESIS is an AI foundry.** It produces agents.

The foundry has one canonical template — **BlackZero** — that all agents are derived from.
Reusable capabilities are packaged as modules. Everything experimental or in-progress lives in `pending/`.

---

## What Is BlackZero?

BlackZero is the locked template at the heart of GENESIS. It is **not** an agent — it is the
genetic blueprint that every agent is built from. It defines the cognitive architecture, subsystem
contracts, and safety policies that all derived agents must follow.

```
BlackZero/
    brain/       — cognitive core (locked to exactly 4 files)
    identity/    — mission and personality template
    memory/      — memory manager interface
    storage/     — SQLite and vector store interfaces
    rag/         — retrieval, indexing, and embedding interfaces
    tools/       — base tool contract and registry
    models/      — model router and provider adapter interfaces
    policies/    — safety rules, governance, permissions
    diagnostics/ — doctor.py (structure) and healthcheck.py (runtime)
    tests/       — brain tests, structure tests, subsystem tests
```

All subsystem files are abstract — they define the contracts that agent implementations must fulfill.

---

## What Is `pending/`?

`pending/` is the quarantine zone. Nothing in this repository is deleted.
Anything legacy, experimental, or uncertain goes into `pending/` until it is reviewed and
deliberately promoted into the correct part of the structure.

---

## Current Structure

```
GENESIS/
    BlackZero/     — canonical AI template
    modules/       — reusable capability modules
    agents/        — AI agent instances derived from BlackZero
    builders/      — scaffolding tools for new agents
    evals/         — evaluation suites
    datasets/      — structured data for agents and RAG
    scripts/       — utility scripts and test runner
    configs/       — system and model configuration files
    docs/          — architecture, rules, specs, guides
    docker/        — containerization support
    pending/       — quarantine for legacy and experimental material
    README.md      — this file
    .gitignore
```

---

## Module Contract

All modules subclass `ModuleBase` from `modules/base.py`. This is the shared ABC that
defines the contract every module must fulfill: HTTP router, health check, lifecycle hooks,
and serialization. Import it with `from modules.base import ModuleBase`.

## Module Registry

| Module | Version | Description |
|--------|---------|-------------|
| `teacher` | 1.0.0 | General AI Tutor — RAG-backed knowledge ingestion and Q&A with citations |
| `tax` | 1.0.0 | US federal tax calculator (2024 / 2025 / 2026 projected) |
| `sdimport` | 1.0.0 | Stable Diffusion metadata extractor + ComfyUI workflow builder |

---

## Running the Doctor

The doctor verifies repository structure. Run it whenever structural changes are made.

```bash
python3 BlackZero/diagnostics/doctor.py
```

Output:
- `DOCTOR: PASS` — repository structure is healthy
- `DOCTOR: FAIL` — lists every violation with clear descriptions

---

## Running Tests

```bash
# All test suites (217 tests)
python3 scripts/run_tests.py

# Specific suites
python3 scripts/run_tests.py --brain       # 100 brain tests
python3 scripts/run_tests.py --structure   # structure + doctor validation
python3 scripts/run_tests.py --subsystems  # subsystem interface tests
python3 scripts/run_tests.py --modules     # module tests (teacher, tax, sdimport)

# Verbose output
python3 scripts/run_tests.py -v
```

---

## Building an Agent from BlackZero

1. Copy the BlackZero structure into `agents/<your_agent>/`
2. Fill in `identity/mission.md` and `identity/personality.yaml`
3. Implement the subsystem ABCs (memory, storage, rag, tools, models) as needed
4. Wire in modules from `modules/` for additional capabilities
5. Never modify BlackZero directly — it is the template, not an instance

See `docs/blackzero_spec.md` for the detailed specification and `docs/ADDING_A_MODULE.md` for the module guide.

---

## Documentation

| File | Purpose |
|------|---------|
| `docs/architecture.md` | How the system fits together |
| `docs/genesis_rules.md` | Official rules — what is and isn't allowed |
| `docs/blackzero_spec.md` | BlackZero template specification |
| `docs/ADDING_A_MODULE.md` | Step-by-step guide to building a module |
