GENESIS ARCHITECTURE
Official Reference Document v1.0

PURPOSE

This document describes the structural blueprint of the Genesis repository.
It explains what each major component is, how components relate to each other,
and how the system fits together as a whole.

For rules governing what is and is not allowed, see genesis_rules.md.
For the detailed specification of the BlackZero template, see blackzero_spec.md.


OVERVIEW

Genesis is an AI foundry. It produces agents.

The foundry has one canonical template: BlackZero.
All agents are derived from BlackZero.
Reusable capabilities are stored as modules.
Reusable tooling is stored as builders, evals, datasets, scripts, and configs.
Everything unclassified or in-progress goes to pending/.


TOP-LEVEL STRUCTURE

Genesis/
    BlackZero/       — the canonical AI template (the genetics of every agent)
    modules/         — reusable capability modules (vision, voice, coding, browsing)
    agents/          — AI instances derived from BlackZero
    builders/        — scaffolding and code generation tools
    evals/           — evaluation suites that measure agent performance
    datasets/        — structured data used by agents, evals, and RAG
    scripts/         — runnable entrypoints and utility scripts
    configs/         — system and model configuration files
    docs/            — all human-readable project guidance
    docker/          — containerization support
    pending/         — quarantine for anything unclassified or in-progress
    README.md        — project entry point
    .gitignore       — excludes runtime data, secrets, and junk


BLACKZERO — THE TEMPLATE

BlackZero is not an agent. It is the locked template that agents are built from.
It defines the structure, cognitive architecture, and subsystem layout
that every agent must follow.

BlackZero/
    brain/           — the cognitive core (locked to four files)
    identity/        — mission and personality definition
    memory/          — memory management logic
    storage/         — persistence and storage adapters
    rag/             — retrieval-augmented generation logic
    tools/           — reusable tool infrastructure
    models/          — model routing and provider integration
    policies/        — safety rules and governance constraints
    diagnostics/     — repo health checks and doctor
    tests/           — structural and behavioral tests


THE BRAIN

The brain is the hardened cognitive core of any agent built from BlackZero.
It is locked to exactly four files with fixed responsibilities:

    loop.py      — runs the continuous cognitive process
    planner.py   — decides what to do next
    executor.py  — carries out the planned action
    router.py    — directs input and output to the right destination

No other files belong in brain/. No logic migrates between these files casually.
All additional complexity is built outside the brain and connected to it.


HOW AGENTS ARE BUILT

An agent is an instance derived from BlackZero.

    1. Start from the BlackZero structure.
    2. Populate identity/ with the agent's specific mission and personality.
    3. Wire in any required modules from modules/.
    4. Add agent-specific logic inside the agent's own folder.
    5. Never modify BlackZero directly.

agents/
    engineer0/       — example: a software engineering agent
    madjanet/        — example: a creative or communications agent
    cranston/        — example: a general-purpose agent
    accountant/      — example: a financial reasoning agent

Each agent folder mirrors the BlackZero structure.
Agent-specific code stays inside the agent folder.


HOW MODULES WORK

Modules are portable capability packages.
They are not agents. They have no identity.
They provide a single capability that any agent can use.

modules/
    vision/          — image and video processing
    voice/           — speech input and output
    coding/          — code generation and execution
    browsing/        — web interaction and retrieval

An agent imports a module to gain that capability.
Modules do not depend on each other.
Modules do not contain agent-specific logic.


HOW BUILDERS WORK

Builders are tools that generate agent structure from BlackZero.
They are used to scaffold new agents quickly and consistently.

builders/
    agent_builder.py     — generates a new agent folder from the BlackZero template
    template_loader.py   — loads and validates BlackZero structure for scaffolding


HOW EVALS WORK

Evals measure agent performance. They are separate from the agents themselves.
An eval suite tests reasoning, tool use, bias, or behavior without being
part of the agent's runtime code.

evals/
    reasoning/       — tests for logical and planning capability
    bias/            — tests for behavioral consistency and fairness
    tools/           — tests for correct tool selection and execution
    outputs/         — generated eval results (gitignored or organized)


DATA FLOW

User input
    → router.py (directs input to the right destination)
    → planner.py (decides what action to take)
    → executor.py (carries out the action)
        → may call tools/ (external capabilities)
        → may call rag/ (retrieval from datasets/)
        → may read/write memory/ and storage/
    → router.py (directs output back to user)


PENDING AND QUARANTINE

pending/ is the intentional quarantine zone.
Nothing is deleted. Everything uncertain, experimental, or unclassified goes here.
Files move out of pending/ only after deliberate review and promotion
into the correct part of the structure.

This prevents loss of history while keeping the main structure clean.


DIAGNOSTICS

BlackZero/diagnostics/doctor.py is the structural health enforcer.
It verifies:
    - root structure matches the approved layout
    - BlackZero folder exists and is correctly structured
    - brain contains exactly four correctly named files
    - all required folders are present
    - pending/ exists

Run doctor.py whenever structural changes are made.
If doctor.py fails, the repository is not considered organized.


DOCUMENT RELATIONSHIPS

    genesis_rules.md   — what is and is not allowed (enforcement)
    architecture.md    — how the system fits together (this document)
    blackzero_spec.md  — the detailed specification of the BlackZero template

These three documents must remain consistent with each other.
If the structure changes, all three must be updated.
