# BlackZero template changelog

Version lives in `VERSION` (single line, semver). `stamp.py` copies that file
into every stamped agent's root and freezes the version + stamp date into the
agent's `config.yaml` under `template:` — so any agent's drift from the
current template is a diff between its own `VERSION`/`config.yaml` and this
file, not a guess.

## 1.4.0 — 2026-07-24

Evidence-ledger redaction, found while wiring a credential-handoff feature
on Cerberus (a stamped agent, not this template — see its own CHANGELOG.md
1.2.0 for the full story). `agent/core/local_tool_bus.py` logs every tool
call's params and result to the on-disk evidence ledger
(`agent/modules/evidence.py`, plain JSONL) with no notion of "this tool
handles secrets." Any stamped agent that adds a tool taking or returning
secret material — a credential store, an API-key manager, anything of that
shape — would hit the same leak: the plaintext lands unredacted in
`evidence_results.jsonl` the first time that tool is called through the
normal chat/tool-bus path, regardless of how carefully that tool's own
storage encrypts at rest.

Changes:
- `agent/core/local_tool_bus.py` — new `SENSITIVE_TOOLS` (tool names whose
  result may contain secret material — empty by default; this template has
  no credential-handling tools of its own) and `SENSITIVE_PARAM_KEYS`
  (param keys redacted regardless of tool name — non-empty by default:
  `password`, `plaintext`, `secret`, `private_key`, `api_key`, `token`).
  `execute()` now redacts `input_summary` per-key and replaces
  `output_summary` with a fixed placeholder for `SENSITIVE_TOOLS` — never
  truncate-and-hope, since a short secret survives any truncation length.
  The full result still reaches the caller/LLM untouched; only the ledger
  write is redacted.
- No stamped agent needs to change anything to pick up the safe default
  (`SENSITIVE_PARAM_KEYS` catches common secret param names out of the
  box); an agent adding its own credential-handling tool should add that
  tool's name to its own copy of `SENSITIVE_TOOLS` — see Cerberus's copy
  of this file for the reference implementation.

## 1.3.0 — 2026-07-15

Fabrication detection closed two gaps, both confirmed live in production
within the same hour, on two different agents:

- `_detect_fabrication` already caught fake write/run/read-file claims but
  had zero coverage for claims about searching/fetching live external
  info. Confirmed live: a deployed agent's `web_search` call failed with
  an SSL error and the model answered with a fabricated, years-stale
  result instead of relaying the failure. Added a pattern set grounded on
  `web_search`/`web_fetch`/`api_call` actually succeeding.
- That fix only covered the shared template's own base tool names. A
  second agent, minutes later, claimed to use a tool called
  "chronicle_status" — which doesn't exist; the real tool is
  "chronicle_stats" — and reported a fabricated 2^31 entry count instead
  of the real count. Added a general check: any explicitly-named tool
  claim ("I used my `<name>` tool") is flagged as fabrication if zero
  tools actually succeeded this turn — not matched by exact name, so a
  real success under a slightly-misremembered name isn't false-flagged.

Both verified against their exact failure scenarios plus false-positive
cases (legitimate tool use, advisory suggestions, plain conversation).

Root cause of why these went unnoticed for a month: `grid_watchdog.py` (the
grid's compliance checker) never checked template version drift or
hardening presence at all, and only ever checked 6 of 22 built agents for
anything. Both fixed same day — see `grid_watchdog.py` R11/R12 and its
expanded `AGENT_CONFIGS` list.

## 1.2.0 — 2026-07-15

Memory (RAG) made genuinely opt-in, not just gracefully-degrading.

Root cause: `requirements.txt` installed `chromadb` + `sentence-transformers`
(torch-class, slow) unconditionally for every stamped agent, and
`agent/modules/__init__.py`'s `enabled("rag", True)` defaulted the module on
in the absence of a `modules.rag` config key — so even agents that never use
semantic recall (e.g. Chronicle, almost entirely deterministic tooling) paid
the install cost on every build. `agent/modules/rag.py` already degraded
cleanly at runtime if Chroma was disabled or failed to init; the dependency
install was the part that wasn't actually optional.

Changes:
- `requirements.txt` — removed `chromadb`/`sentence-transformers`.
- `requirements-memory.txt` (new) — those two lines. Spliced into a stamped
  agent's `requirements.txt` only when requested.
- `config.yaml` — added explicit `modules.rag.enabled: false`, flipping the
  template default from implicit-on to opt-in (matches the `autonomy.loops`
  philosophy already in this template).
- `stamp.py` — new `memory: bool = False` param: appends
  `requirements-memory.txt` into the stamped `requirements.txt` and sets
  `modules.rag.enabled: true` in the stamped `config.yaml` when true. New
  `--memory` CLI flag.
- `build_agent.py` — manifest gains an optional `memory: bool` field, threaded
  into `stamp()`; `verify()` asserts the splice actually happened when
  `memory: true` was requested.

Only affects future stamps — each agent's `config.yaml`/`requirements.txt`
are frozen copies from stamp time, so already-deployed agents are unaffected.

## 1.1.0 — 2026-07-14

Origin/provenance hardening, from the Engineer0 hallucination-and-spoofing
audit (2026-07-14: she executed a real write_file/shell sequence in response
to an automated E2E test message that arrived indistinguishable from a real
instruction from Darnie).

Root cause: `from_agent` had no required, verified value anywhere in the
pipeline. It defaulted to `"user"` at every layer (API request model, graph
state, tool-bus context), any caller could set it to anything, autonomous
loops never set it at all (silently inheriting the "user" default), and
persisted memory hardcoded every turn's role to `"human"` regardless of
actual origin — permanently erasing provenance and reinforcing the confusion
on every future recall.

Changes:
- `agent/api/server.py` — `ChatRequest.from_agent` default changed from
  `"user"` to `"unverified"`. Fail closed, not open.
- `agent/core/graph.py`:
  - `recall` node now pins `from_agent` to `"unverified"` if the caller left
    it unset, instead of letting it silently read as `"user"` later.
  - `recall` node honors an explicit `tool_required` passed in by the caller
    (task_loop/todo_loop) instead of always recomputing it from message text.
  - Removed the `"execute this task now"` literal-prefix sniff from
    `_requires_tool_use()` — that was string content the model itself could
    also read, not a real signal, and it was todo_loop's only way to force
    tool enforcement short of a real state flag.
  - `respond` node passes real `from_agent` into `mind_state.save()` instead
    of leaving it to default.
  - `tool` node passes `from_agent` through to `local_tool_bus.execute()` as
    `origin`.
- `agent/core/local_tool_bus.py` — new origin gate, checked before routing/
  quarantine/policy: `HIGH_RISK_TOOLS` (shell, python, write_file,
  patch_file, git_add/commit/push, adb, assign_api/revoke_api) require
  `origin` to be one of `TRUSTED_ORIGINS` (`user`, `loop:task_loop`,
  `loop:todo_loop`). Everything else — unverified origin, raw agent-to-agent
  messages that never went through the reviewed task queue — is denied
  before it reaches the executor. `ExecutionContext.agent_id` (previously
  constructed and never used) now actually carries the origin.
- `agent/modules/evidence.py` — `ResultRecord`/`record_result()` gained an
  `origin` field, so the evidence ledger has a real audit trail of who asked
  for every tool call, including denials.
- `agent/modules/mind_state.py` — `save()`/`_local_save()` take `from_agent`
  and store the real origin as the row's `role` (`"human"` only when
  `from_agent == "user"`; otherwise `"origin:<from_agent>"`). Recalled context
  now shows provenance instead of relabeling every autonomous task, self-test,
  and inter-agent message as a human conversation.
- `agent/core/loops.py` — `task_loop` and `todo_loop` now pass
  `from_agent="loop:task_loop"` / `"loop:todo_loop"` and
  `tool_required=True` explicitly into `graph.invoke()`, instead of omitting
  `from_agent` (defaulting to trusted) and relying on prompt-text sniffing
  for tool enforcement.

Known gap NOT fixed here (out of this repo's scope): PlugOps itself must
stamp `from_agent` server-side from the authenticated connection identity
before forwarding a message to any agent, and the human-chat ingress (the
Telegram relay path) must be the only caller ever allowed to assert
`from_agent: "user"`. Until that lands in PlugOps, an unauthenticated caller
that can reach an agent's `/api/chat` directly can still claim `from_agent:
"user"` — the fixes in this version close the "loops/self-tests/memory
silently inherit trust" hole and add a real deny-by-default gate on
high-risk tools, but they do not by themselves authenticate the human
channel. Track alongside the existing unauthenticated `/api/tools/execute`
finding.

## 1.0.0 — baseline

Pre-audit template. No recorded version history before this file existed;
treat as the implicit starting point for every agent stamped before
2026-07-14.
