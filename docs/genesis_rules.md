GENESIS ORGANIZATION RULES
(OFFICIAL LOCKED VERSION)
v1.2

------------------------------------------------------------
PRIME RULE
------------------------------------------------------------

If it does not clearly belong in the official structure, it goes into pending/.

This one rule governs all decisions in this repository. Every rule below is
a specific application of it. When in doubt, stop reading and use pending/.


------------------------------------------------------------
PURPOSE
------------------------------------------------------------

Genesis is a clean AI foundry repository.

It exists to hold:
- the canonical AI template (BlackZero)
- reusable modules
- reusable builders
- reusable evaluations
- reusable documentation

It does NOT exist to hold random experiments, old apps, mixed agent code, or
drifting architecture.

Everything in Genesis must either:
1) belong to the approved structure, or
2) go into pending/


------------------------------------------------------------
1. ROOT STRUCTURE RULE
------------------------------------------------------------

The Genesis root may contain ONLY these entries:

BlackZero/
modules/
agents/
builders/
evals/
datasets/
scripts/
configs/
docs/
docker/
pending/
README.md
.git
.gitignore

No other root-level files or folders are allowed.
Anything that does not belong goes into pending/.


------------------------------------------------------------
2. PENDING RULE
------------------------------------------------------------

pending/ is the quarantine folder.

- Nothing is deleted.
- Anything legacy, experimental, uncertain, duplicate, or unclassified goes here.
- Files may only leave pending/ after deliberate review.
- Never overwrite files when moving into pending/. If a name conflict exists,
  preserve both copies by renaming safely.

pending/ preserves history and prevents accidental loss.


------------------------------------------------------------
3. BLACKZERO RULE
------------------------------------------------------------

BlackZero is the canonical AI template.

BlackZero must remain stable and organized.

BlackZero may contain ONLY:

brain/
identity/
memory/
storage/
rag/
tools/
models/
policies/
diagnostics/
tests/

No additional top-level BlackZero folders may be added without revising this
rules file.

BlackZero is the genetics of the AI. It should remain compact, inspectable,
and reusable. It is a read-only template — never instantiated directly, never
modified by automated processes.


------------------------------------------------------------
4. BRAIN RULE
------------------------------------------------------------

BlackZero/brain is locked.

It must contain EXACTLY these four files:

loop.py     — the main cognitive cycle / run loop
planner.py  — decides what to do next
executor.py — carries out the decided action
router.py   — directs input/output to the right place

No additional files may be added to BlackZero/brain.
No files may be renamed.
No files may be nested under brain/.
Logic may not migrate between files — planner logic stays in planner.py,
executor logic stays in executor.py.

The brain is the hardened cognitive core.
All complexity must be added OUTSIDE the brain.


------------------------------------------------------------
5. IDENTITY RULE
------------------------------------------------------------

BlackZero/identity must contain:

mission.md       — the AI's purpose, scope, and behavioral constraints
personality.yaml — tone, communication style, and character traits

These define the AI's fixed core identity.


------------------------------------------------------------
6. MODULES RULE
------------------------------------------------------------

modules/ holds reusable standalone code units.

Each module must:
- solve one problem
- be independently testable
- have no dependency on a specific agent

Modules are infrastructure. Agents consume them.


------------------------------------------------------------
7. AGENTS RULE
------------------------------------------------------------

agents/ holds all agent implementations.

Each agent gets its own subfolder: agents/<agent_name>/

Each agent folder must follow the BlackZero structure.
Agents are built in GENESIS first. They graduate to Botico only after
passing full validation.

No agent code lives at the root of agents/.


------------------------------------------------------------
8. BUILDERS RULE
------------------------------------------------------------

builders/ holds scripts and tools that generate or scaffold agents,
modules, or other repo artifacts.

Builders produce things. They are not agents themselves.


------------------------------------------------------------
9. EVALS RULE
------------------------------------------------------------

evals/ holds evaluation harnesses for testing agent behavior,
model output quality, and system performance.

Evals are not unit tests. Unit tests live inside agent or module folders.
Evals test behavior at a higher level.


------------------------------------------------------------
10. DATASETS RULE
------------------------------------------------------------

datasets/ holds training data, prompt libraries, and reference corpora.

No model weights. No large binaries unless explicitly approved.
Large files use git-lfs or external storage with a pointer file here.


------------------------------------------------------------
11. SCRIPTS RULE
------------------------------------------------------------

scripts/ holds one-off automation, migration, and maintenance scripts.

Scripts are not agents. Scripts are not modules.
A script that grows into a reusable system moves to modules/.


------------------------------------------------------------
12. CONFIGS RULE
------------------------------------------------------------

configs/ holds environment configs, model configs, and system settings.

No secrets. No API keys. No credentials.
Secrets go in environment variables or a secrets manager — never in the repo.


------------------------------------------------------------
13. DOCS RULE
------------------------------------------------------------

docs/ holds human-readable documentation.

Required files:
- architecture.md
- genesis_rules.md
- blackzero_spec.md

Docs must stay accurate. A doc that no longer reflects reality must be
updated or moved to pending/.


------------------------------------------------------------
14. DOCKER RULE
------------------------------------------------------------

docker/ holds Dockerfiles and supporting docker configs.

Allowed: Dockerfile, supporting docker configs.
Not allowed: random runtime data, duplicate app code, hidden project structure.

docker/ packages the project. It does not replace it.


------------------------------------------------------------
15. README RULE
------------------------------------------------------------

README.md must clearly explain:
- what Genesis is
- what BlackZero is
- what pending/ is
- the current top-level structure
- how to run the doctor

README must stay simple and accurate.


------------------------------------------------------------
16. PLACEHOLDER RULE
------------------------------------------------------------

During skeleton phase, all files except doctor.py may remain empty.
Placeholder files keep the structure visible.

Do not invent business logic early.
Do not fill random files just to fill them.

The skeleton comes first. Real logic comes later.


------------------------------------------------------------
17. DISCIPLINE RULE
------------------------------------------------------------

Before adding anything new, ask:
1) Does this already belong in an existing folder?
2) Is this a real subsystem or just an experiment?
3) Is there already a canonical version of this elsewhere in the repo?
4) Should it go to pending/ first?

If uncertain on any count, put it in pending/.

One canonical place for each system. No duplicate brains, doctors, routers,
or registries. No junk accumulation — .DS_Store, __pycache__, loose .pyc
files, random zips, abandoned logs, and unnamed exports must be gitignored
or quarantined.


------------------------------------------------------------
18. HYGIENE RULE
------------------------------------------------------------

Every file and folder name must explain its function at a glance.

Good: memory_manager.py, sqlite_store.py, model_router.py
Bad:  temp.py, test2.py, stuff.py, newfile.py

When recovering old work from pending/:
1) inspect it
2) decide its category
3) move only the useful part into the correct folder
4) leave the rest in pending/

Promote carefully. Do not resurrect chaos.


------------------------------------------------------------
19. CHANGE RULE
------------------------------------------------------------

Any structural change must update:
- docs/genesis_rules.md
- README.md
- doctor.py

If the rules change, the documentation and the doctor must change too.
Otherwise structure and enforcement drift apart.


------------------------------------------------------------
20. SUCCESS RULE
------------------------------------------------------------

The repository is considered organized only when:

- root matches the approved structure
- pending/ contains all quarantined legacy material
- BlackZero exists and matches the locked layout
- brain contains exactly four correctly named files with correct responsibilities
- doctor.py passes
- all stray files are removed or quarantined

That is the definition of "organized."


------------------------------------------------------------
21. PROVING GROUND RULE
------------------------------------------------------------

GENESIS is the mandatory proving ground for all development.

Nothing moves to Botico until it has been fully built, tested, and validated
inside GENESIS. All agents, modules, and communication infrastructure must
pass their full test suite before graduation.

Once an artifact graduates to Botico, it is sealed. It cannot be modified
by agents, automated processes, or casual edits. Changes require a new
GENESIS cycle.

Botico is production. GENESIS is where things earn the right to go there.


------------------------------------------------------------
22. VALIDATION RULE
------------------------------------------------------------

No agent reports a task complete without proof.

Before any agent closes out a task, it must:
1) Run all relevant tests for the work performed
2) Return actual test output — pass/fail counts, errors, results
3) Only then report success

Saying "done" without test evidence is a violation of this rule.

This applies to all agents: Engineer0, Cerberus, Accountant, and any
future agent built in GENESIS.

An agent that cannot validate its own work must escalate — not close.
