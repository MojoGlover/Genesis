GENESIS ORGANIZATION RULES (OFFICIAL LOCKED VERSION) v1.1
PRIME RULE
If it does not clearly belong in the official structure, it goes into pending/.
This one rule governs all decisions in this repository. Every rule below is a specific application of it. When in doubt, stop reading and use pending/.
PURPOSE
Genesis is a clean AI foundry repository.
It exists to hold:
* the canonical AI template (BlackZero)
* reusable modules
* reusable builders
* reusable evaluations
* reusable documentation
It does NOT exist to hold random experiments, old apps, mixed agent code, or drifting architecture.
Everything in Genesis must either:
1. belong to the approved structure, or
2. go into pending/
1. ROOT STRUCTURE RULE
The Genesis root may contain ONLY these entries:
BlackZero/ modules/ agents/ builders/ evals/ datasets/ scripts/ configs/ docs/ docker/ pending/ README.md .git .gitignore
No other root-level files or folders are allowed. Anything that does not belong goes into pending/.
1. PENDING RULE
pending/ is the quarantine folder.
* Nothing is deleted.
* Anything legacy, experimental, uncertain, duplicate, or unclassified goes here.
* Files may only leave pending/ after deliberate review.
* Never overwrite files when moving into pending/. If a name conflict exists, preserve both copies by renaming safely.
pending/ preserves history and prevents accidental loss.
1. BLACKZERO RULE
BlackZero is the canonical AI template — the genetics of every agent. It must remain stable, compact, inspectable, and reusable.
BlackZero may contain ONLY:
brain/ identity/ memory/ storage/ rag/ tools/ models/ policies/ diagnostics/ tests/
No additional top-level BlackZero folders may be added without revising this rules file.
1. BRAIN RULE
BlackZero/brain is locked.
It must contain EXACTLY these four files, each with a fixed responsibility:
loop.py — the main cognitive cycle; runs the agent's continuous process planner.py — decides what to do next given current state and goals executor.py — carries out the action decided by the planner router.py — directs input and output to the correct internal destination
No additional files may be added. No files may be renamed. No files may be nested under brain/. Logic must not migrate between these files casually — if planner logic ends up in executor.py, that is a violation.
The brain is the hardened cognitive core. All complexity must be added OUTSIDE the brain.
1. IDENTITY RULE
BlackZero/identity must contain:
mission.md — the AI's fixed purpose and operating mandate personality.yaml — tone, behavioral traits, and communication style
These files define the AI's core identity and must not be casually rewritten, filled with generated junk, or used as temporary scratch space.
1. MEMORY RULE
BlackZero/memory holds memory management logic only.
Allowed: memory manager, memory schemas, memory interfaces.
Not allowed: experiment dumps, random transcripts, loose notes, training exports.
Runtime data belongs in storage/ or datasets/, not inside memory source files.
1. STORAGE RULE
BlackZero/storage contains storage logic only.
Allowed: sqlite store logic, vector store logic, storage adapters.
Not allowed: loose .db files, backup dumps, exported artifacts scattered around the repo.
Any database or generated runtime data must live in a controlled subfolder or be gitignored.
1. RAG RULE
BlackZero/rag contains retrieval logic only.
Allowed: retrievers, embedding routers, indexing helpers.
Not allowed: datasets, embedded documents, notes, random evaluation files.
Data goes into datasets/ or evals/, not here.
1. TOOLS RULE
BlackZero/tools contains reusable tool infrastructure.
Allowed: tool registry, base tool interface, tool execution helpers.
Not allowed: one-off scripts, random experiments, project-specific hacks.
Any temporary or experimental tool must go to pending/ until promoted.
1. MODELS RULE
BlackZero/models contains model routing and provider integration.
Allowed: model router, provider adapter definitions.
Not allowed: training data, transcripts, prompt experiments, mixed app logic.
Provider-specific code must stay compartmentalized.
1. POLICIES RULE
BlackZero/policies contains explicit policy files only.
Allowed: safety rules, permissions, governance constraints.
Policies must remain readable and separate from implementation logic. Do not bury policy logic inside random source files if it belongs here.
1. DIAGNOSTICS RULE
BlackZero/diagnostics contains repo and system health logic.
doctor.py is mandatory and must enforce:
1. root structure validity
2. BlackZero presence
3. brain exact-file rule (four files, correct names)
4. required folder existence
5. pending/ existence
healthcheck.py may contain future runtime checks.
Diagnostics must never be removed.
1. TESTS RULE
BlackZero/tests contains tests only.
Required at minimum:
* brain\_tests.py — verifies brain contains exactly four correctly named files
* structure\_tests.py — verifies required folders exist and doctor passes
No experimental notebooks or ad hoc scratch files belong here.
1. MODULES RULE
modules/ contains reusable capability modules.
Allowed: vision/, voice/, coding/, browsing/
Rules:
* one capability per module folder
* no agent identity inside modules
* no root-level loose module files
* modules must remain portable
A module is a capability, not an agent.
1. AGENTS RULE
agents/ contains actual AI instances built from BlackZero.
Examples: engineer0/, madjanet/, cranston/, accountant/
Rules:
* agents inherit from BlackZero structure
* agents must not redefine the entire core architecture
* agent-specific code stays inside the agent folder
* no agent may modify BlackZero directly
BlackZero is the template. agents/ are derived instances.
1. BUILDERS RULE
builders/ contains code generation and scaffolding tools.
Allowed: agent\_builder.py, template\_loader.py
Not allowed: runtime AI behavior, random experiments, data dumps.
Builders generate structure. They are not the structure.
1. EVALS RULE
evals/ contains evaluation logic and suites.
Allowed: reasoning tests, bias tests, tool tests.
Rules:
* evaluation data must be organized by test type
* no random logs or outputs at root
* generated eval outputs go in a dedicated output subfolder or are gitignored
evals/ measures the AI. It is not part of the brain.
1. DATASETS RULE
datasets/ contains structured data only.
Allowed: curated datasets, training examples, retrieval corpora, benchmark input sets.
Rules:
* datasets must be named clearly
* no mystery files or one-off dumps without description
* every dataset must include a short README or metadata note
Data must not be scattered throughout the repo.
1. SCRIPTS RULE
scripts/ contains runnable utility scripts.
Allowed: launch\_agent.py, run\_evals.py, system\_report.py
Rules:
* scripts are entrypoints or utilities only
* do not put library logic here if it belongs elsewhere
* do not duplicate functionality already in BlackZero or modules
scripts/ is for execution helpers, not architecture.
1. CONFIGS RULE
configs/ contains configuration files only.
Allowed: model\_config.yaml, system\_config.yaml
Rules:
* configs must remain human-readable
* no secrets committed to git
* no random backups or copies
* config names must be explicit
Environment secrets belong in .env files ignored by git.
1. DOCS RULE
docs/ contains all human-readable project guidance.
Required files:
* architecture.md
* genesis_rules.md
* blackzero_spec.md
Rules:
* docs must not contradict each other
* new rules must be added by updating docs, not hidden in chat history
* docs are the source of truth, not memory
If the project changes, docs must be updated immediately.
1. DOCKER RULE
docker/ contains containerization support only.
Allowed: Dockerfile, supporting docker configs.
Not allowed: random runtime data, duplicate app code, hidden project structure.
docker/ packages the project. It does not replace it.
1. README RULE
README.md must clearly explain:
* what Genesis is
* what BlackZero is
* what pending/ is
* the current top-level structure
* how to run the doctor
README must stay simple and accurate.
1. PLACEHOLDER RULE
During skeleton phase, all files except doctor.py may remain empty. Placeholder files keep the structure visible.
Do not invent business logic early. Do not fill random files just to fill them.
The skeleton comes first. Real logic comes later.
1. DISCIPLINE RULE
Before adding anything new, ask:
1. Does this already belong in an existing folder?
2. Is this a real subsystem or just an experiment?
3. Is there already a canonical version of this elsewhere in the repo?
4. Should it go to pending/ first?
If uncertain on any count, put it in pending/.
One canonical place for each system. No duplicate brains, doctors, routers, or registries. No junk accumulation — .DS\_Store, pycache, loose .pyc files, random zips, abandoned logs, and unnamed exports must be gitignored or quarantined.
1. HYGIENE RULE
Every file and folder name must explain its function at a glance.
Good: memory\_manager.py, sqlite\_store.py, model\_router.py Bad: temp.py, test2.py, stuff.py, newfile.py
When recovering old work from pending/:
1. inspect it
2. decide its category
3. move only the useful part into the correct folder
4. leave the rest in pending/
Promote carefully. Do not resurrect chaos.
1. CHANGE RULE
Any structural change must update:
* docs/genesis\_rules.md
* README.md
* doctor.py
If the rules change, the documentation and the doctor must change too. Otherwise structure and enforcement drift apart.
1. SUCCESS RULE
The repository is considered organized only when:
* root matches the approved structure
* pending/ contains all quarantined legacy material
* BlackZero exists and matches the locked layout
* brain contains exactly four correctly named files with correct responsibilities
* doctor.py passes
* all stray files are removed or quarantined
That is the definition of "organized."
