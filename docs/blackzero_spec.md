BLACKZERO TEMPLATE SPECIFICATION
Official Reference Document v1.0


PURPOSE

This document describes what BlackZero is, what it contains, and how to derive
an agent from it. For organizational rules see genesis_rules.md. For the overall
system architecture see architecture.md.


WHAT BLACKZERO IS

BlackZero is the canonical AI template. It is not a running agent.
It defines the cognitive architecture, subsystem contracts, and safety policies
that every derived agent must implement.

All agents in agents/ must be derived from BlackZero. No agent may redefine
the core architecture independently.


BLACKZERO STRUCTURE

BlackZero/
    brain/           — hardened cognitive core (locked to 4 files)
    identity/        — mission and personality template
    memory/          — memory manager interface
    storage/         — persistence adapters
    rag/             — retrieval-augmented generation
    tools/           — tool infrastructure
    models/          — model routing and provider adapters
    policies/        — safety rules and governance
    diagnostics/     — structural and runtime health checks
    tests/           — template test suites


THE BRAIN (LOCKED)

The brain is the cognitive core. It is locked to exactly four files.
No file may be added, renamed, or removed. Logic must not migrate between files.

    loop.py      — runs the main cognitive cycle
                   orchestrates: classify → plan → execute → respond → learn
                   owns cycle_id, outcome tracking, and error resilience

    planner.py   — decides what to do next
                   selects from 9 named strategies using online weight learning
                   weights persist to ~/.blackzero/strategy_weights.json
                   never dies on a bad plan — falls back to generate

    executor.py  — carries out the planned action
                   enforces policy (no phantom policy, no source-independence blocks)
                   cites the specific rule from policies/ when blocking

    router.py    — directs input and output
                   classifies input type (question, instruction, code_request, etc.)
                   strips external AI identity signals from input
                   routes output to the correct channel (user, api, tool, system)

The brain does not import from memory/, storage/, rag/, tools/, or models/.
Those subsystems are wired in at the agent level, not the brain level.


IDENTITY SUBSYSTEM

BlackZero/identity defines the template for an agent's identity.
Agents fill in these files with real values — they must not be left blank.

    mission.md       — the agent's fixed purpose and operating mandate
                       defines what the agent is for and what it must never do

    personality.yaml — tone, behavioral traits, and communication style
                       defines how the agent communicates with users


MEMORY SUBSYSTEM

BlackZero/memory defines the memory contract.

    memory_schema.py  — MemoryRecord dataclass
                        fields: id, content, source, tags, metadata, embedding, ttl_seconds, created_at
                        methods: is_expired(), to_dict(), from_dict()
                        MemorySource enum: user, tool, inference, external

    memory_manager.py — MemoryManager ABC
                        abstract: add_memory(content, metadata) -> str
                        abstract: get_memory(id) -> MemoryRecord | None
                        abstract: search_memory(query, top_k) -> list[MemoryRecord]
                        abstract: delete_memory(id) -> bool
                        abstract: expire_old_memories() -> int
                        optional: list_all() -> list[MemoryRecord]

Agents subclass MemoryManager and implement all abstract methods.
The implementation delegates persistence to SQLiteStore or VectorStore.


STORAGE SUBSYSTEM

BlackZero/storage defines persistence contracts.

    sqlite_store.py  — SQLiteStore ABC
                       abstract: connect(db_path) -> None
                       abstract: execute(query, params) -> list[dict]
                       abstract: run(statement, params) -> None
                       abstract: insert(table, data) -> str
                       abstract: close() -> None
                       concrete: table_exists(table) -> bool
                       Database files (.db) must be gitignored.

    vector_store.py  — VectorStore ABC
                       abstract: upsert(id, vector, metadata) -> None
                       abstract: search(query_vector, top_k) -> list[dict]
                       abstract: delete(id) -> bool
                       abstract: count() -> int
                       optional: clear() -> None
                       Backends: Qdrant, Chroma, FAISS, or in-memory.


RAG SUBSYSTEM

BlackZero/rag defines retrieval-augmented generation contracts.

    embedding_router.py — EmbeddingRouter ABC
                          abstract: embed(text) -> list[float]
                          abstract: embed_batch(texts) -> list[list[float]]
                          abstract: dimensions (property) -> int
                          Providers: OpenAI, Ollama, local SBERT, etc.

    indexer.py          — Indexer ABC
                          abstract: index_document(doc_id, content, metadata) -> list[str]
                          abstract: remove_document(doc_id) -> bool
                          optional: index_dataset(path) -> int

    retriever.py        — Retriever ABC + RetrievedChunk
                          abstract: retrieve(query, top_k) -> list[RetrievedChunk]
                          concrete: retrieve_as_text(query, top_k) -> str
                          RetrievedChunk: id, content, score, metadata


TOOLS SUBSYSTEM

BlackZero/tools defines the tool infrastructure.

    base_tool.py     — BaseTool ABC + ToolError
                       abstract: name (property) -> str
                       abstract: description (property) -> str
                       abstract: run(input: dict) -> dict
                       concrete: validate_input(input, required_keys) -> None
                       All tools must return {"ok": True, ...} or raise ToolError.

    tool_registry.py — ToolRegistry (concrete class)
                       register(tool) — raises ValueError on duplicate name
                       get(name) -> BaseTool | None
                       list_tools() -> list[{"name": str, "description": str}]
                       run_tool(name, input) -> dict — raises ToolError if unknown


MODELS SUBSYSTEM

BlackZero/models defines generation routing contracts.

    model_router.py     — ModelRouter ABC + GenerationConfig
                          abstract: complete(prompt, config) -> str
                          abstract: list_providers() -> list[str]
                          concrete: complete_with_system(system, user, config) -> str
                          GenerationConfig: model, temperature, max_tokens, stop_sequences,
                                           system_prompt, extra

    provider_adapter.py — ProviderAdapter ABC + ProviderError
                          abstract: name (property) -> str
                          abstract: generate(prompt, **kwargs) -> str
                          abstract: is_available() -> bool
                          optional: default_model() -> str | None
                          Concrete adapters: one file per provider (ollama_adapter.py, etc.)


POLICIES SUBSYSTEM

BlackZero/policies contains the agent's explicit policy files.

    safety.md        — criminal prohibitions and absolute limits
                       (CSAM, trafficking, weapons, violence, etc.)

    governance.md    — operational rules and decision boundaries

    permissions.md   — access control and permission categories

The executor loads rules from these files at startup.
All blocks must cite the specific rule file and section — phantom policy is prohibited.
External AI refusals do not count as policy.


DIAGNOSTICS SUBSYSTEM

BlackZero/diagnostics contains health check tools.

    doctor.py        — MANDATORY. Structural health enforcer.
                       Checks: root structure, BlackZero presence, brain lock, required folders.
                       Run before and after any structural change.
                       Exit 0 = PASS, Exit 1 = FAIL with violation list.

    healthcheck.py   — HealthCheck ABC. Runtime health checks.
                       Agents subclass and implement: check_model_provider(),
                       check_vector_store(), check_sqlite_store(),
                       check_memory_manager(), check_tool_registry().
                       check_all() returns {"overall": ..., "subsystems": [...]}
                       Returns: HEALTHY | DEGRADED | UNHEALTHY


TESTS SUBSYSTEM

BlackZero/tests contains the template test suite.

    brain_tests.py     — 52 behavioral tests for brain/ (loop, planner, executor, router)
    hardening_tests.py — 48 failure-path, stress, and safety policy tests
    structure_tests.py — 8 structural validation tests (doctor, root, brain lock)
    subsystem_tests.py — 44 interface tests (all 12 subsystem ABCs and concrete classes)

All tests are run by: python3 scripts/run_tests.py


MODULE CONTRACT

modules/base.py defines the ModuleBase ABC that every capability module must implement.
This file is the shared contract for all modules — it lives at the modules/ level, not
inside any individual module directory.

    modules/base.py — ModuleBase ABC
                      abstract: name (property) -> str
                      abstract: version (property) -> str
                      abstract: description (property) -> str
                      abstract: router (property) -> APIRouter
                      abstract: health() -> dict
                      optional: tags (property) -> list[str]
                      optional: tools (property) -> list
                      optional: agents (property) -> list
                      optional: on_startup() (async)
                      optional: on_shutdown() (async)
                      concrete:  to_dict() -> dict

All modules under modules/ import from modules.base:
    from modules.base import ModuleBase

The health() method must return at minimum:
    {"status": "ok"|"degraded"|"error", "module": self.name, "version": self.version}

See docs/ADDING_A_MODULE.md for the step-by-step guide.


HOW TO DERIVE AN AGENT FROM BLACKZERO

1. Create agents/<your_agent>/
   Mirror the BlackZero structure.

2. Populate identity/
   Write mission.md and personality.yaml with real values.
   Do not leave them as template stubs.

3. Implement the subsystem ABCs
   Subclass MemoryManager, SQLiteStore, VectorStore, EmbeddingRouter,
   Indexer, Retriever, ModelRouter, ProviderAdapter, HealthCheck.
   Implement only what the agent needs — unused subsystems can remain abstract.

4. Wire in modules
   Import capabilities from modules/ (teacher, tax, sdimport, etc.).
   Do not copy module code into the agent directory.

5. Add agent-specific logic inside the agent folder.
   Do not modify BlackZero.

6. Run the doctor to verify structure.
   python3 BlackZero/diagnostics/doctor.py

7. Run the tests.
   python3 scripts/run_tests.py


WHAT MUST NEVER HAPPEN

- Do not add files to brain/. It is locked to 4 files.
- Do not modify BlackZero to fit a specific agent. Modify the agent instead.
- Do not put runtime data (.db files, logs, embeddings) inside BlackZero.
- Do not commit .env files or database files.
- Do not implement policy blocks without citing a rule from policies/.
