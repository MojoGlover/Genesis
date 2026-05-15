# BlackZero Constitution

**Version:** 2.0  
**Authority:** This document governs all BlackZero-derived agents. It overrides convenience, precedent, and habit.

---

## The Guiding Idea

The model is the brain. APIs, tools, registries, routers, memories, satellites, and endpoints are limbs, senses, transport, and environment.

The brain reasons. The system decides how capabilities are resolved, authorized, executed, recorded, and verified.

---

## Core Doctrine

**No hardwiring.** Nothing location-sensitive is hardcoded. Paths, hosts, models, endpoints, tools, memory stores, and satellite nodes resolve through registry, config, router, or environment. If it would break when a device moves, it is wrong.

**Registry-backed indirection.** Every capability has a stable logical name and a movable implementation. If a model, endpoint, tool, or path moves, the agent is not rewritten — the registry entry is updated.

**Brain and tool separation.** The brain requests capabilities by logical name. It does not import provider SDKs, call tools directly, or contain raw endpoint URLs. The tool bus validates, authorizes, executes, and returns evidence. These responsibilities never cross.

**Proof before claiming.** Unverified assumptions are not facts. Important claims either have evidence, are labeled as inference, or are withheld. "I think" and "I saw" are different statements.

**Tool-result bookkeeping.** Tool outputs become structured result objects. They do not disappear into conversational context. Future reasoning can reference them by id.

**Lifecycle-aware routing.** Components have lifecycle state separate from connectivity. Active, experimental, quarantined, retired, archived, disconnected, and unhealthy are different states. Broken does not mean deleted. Moved does not mean abandoned.

**Policy-gated action.** Risky, irreversible, private, financial, public, or destructive actions pass through policy before execution — not after.

**Repair over deletion.** Broken or displaced models, tools, and connectors are quarantined or marked for repair before being discarded.

**Computer Black loyalty.** The template preserves the user's intent, context, and architecture. It minimizes hallucination, avoids pretending, and favors inspectable work over hidden magic.

---

## The Operating Contract

Every BlackZero-derived agent obeys this contract:

1. Resolve capabilities by logical name.
2. Route requests through policy.
3. Execute through adapters.
4. Record every result.
5. Bind claims to evidence.
6. Preserve lifecycle intent.
7. Make architectural violations testable.

If code violates this contract, the template makes that violation obvious — via contract tests, not runtime surprises.

---

## System Boundaries

### Brain interface
Interprets user intent, decides the next goal, requests capabilities by logical name, reads normalized observations, evaluates whether evidence is sufficient. The brain may ask for `github.search` or `model.generate_fast`. It does not call GitHub or select a provider endpoint.

### Registry interface
Resolves logical names into capabilities. Stores model, tool, endpoint, memory, and satellite manifests. Stores lifecycle state. Provides lookup by name, kind, tags, locality, status, policy, and mode. The anti-hardwiring layer.

### Policy interface
Decides whether a requested capability can run in the current context. Enforces user approvals, blocks destructive actions, separates dev from production, restricts quarantined or retired components. Policy is evaluated before execution.

### Router interface
Chooses the best capability for the request. Matches intent to capability, chooses between local and remote execution, evaluates cost/latency/risk/privacy/health. Every routing decision is explainable and logged.

### Tool bus interface
The only execution path for tools and APIs. Validates input schemas, injects credentials safely, executes adapters, retries where appropriate, normalizes success and failure objects, records timing and side effects, returns structured results to working memory. The brain never calls tools directly.

### Evidence interface
Records what the system actually knows. Stores observations from tools, APIs, files, user input, and memory. Tracks timestamps, provenance, and confidence. Binds claims to supporting observations. Marks stale, inferred, unverified, or contradicted information.

### Lifecycle interface
Tracks component state independent of connectivity. Prevents routing through excluded states. Preserves repair history. Supports re-admission after triage.

---

## Capability Manifest (required fields)

Every model, tool, endpoint, memory source, and satellite declares itself with a manifest before its adapter exists.

```yaml
id: <logical.name>          # stable, dot-namespaced, never changes
kind: tool | model | endpoint | memory | satellite
name: Human-readable name
status: active | experimental | quarantined | retired | archived
lifecycle: active | experimental | quarantined | retired | archived | repairable
adapter: adapters.<module>.<class>   # implementation pointer
risk_level: none | low | medium | high | critical
side_effects: none | local | remote | destructive | financial | public
allowed_modes:
  - explore | plan | act | repair | audit | quarantine
policy:
  confirmation_required: false | true | conditional
  blocked_in: []
```

The manifest is the first artifact. The adapter is the second.

---

## Adapter Standard

Every adapter exposes the same three-method contract:

```python
class CapabilityAdapter:
    id: str

    def validate(self, input: dict) -> ValidationResult:
        """Fail fast on bad input. Never execute with invalid input."""

    def execute(self, input: dict, context: ExecutionContext) -> ExecutionResult:
        """Do the work. Record timing and side effects."""

    def normalize(self, raw_output: object) -> NormalizedResult:
        """Return a stable result object. Raw output may be stored separately."""
```

Adapters do not decide policy. Adapters do not choose themselves. Adapters do not write to long-term memory. Adapters fail loudly and structurally.

---

## Agent Modes

| Mode | Purpose | Blocks |
|------|---------|--------|
| `explore` | Read-only context gathering | All writes, side effects, deletions |
| `plan` | Turn context into proposed action path | Execution unless explicitly approved |
| `act` | Perform approved reversible work | Destructive actions, financial actions |
| `repair` | Fix broken components, preserve intent | Permanent deletion without user approval |
| `audit` | Verify architecture and policy compliance | — |
| `quarantine` | Isolate questionable capabilities | All routing through quarantined component |

---

## Result Object Schema

```json
{
  "id": "result_<timestamp>_<seq>",
  "capability_id": "<logical.name>",
  "status": "success | failure | partial",
  "observed_at": "<iso8601>",
  "input_summary": "...",
  "output_summary": "...",
  "raw_ref": "storage://results/<id>.json",
  "side_effects": "none | ...",
  "evidence_created": ["evidence_<id>"],
  "usable_for_claims": true | false
}
```

---

## Evidence Record Schema

```json
{
  "id": "evidence_<timestamp>_<seq>",
  "claim": "...",
  "source_type": "tool | api | file | user | memory",
  "source_ref": "...",
  "observed_at": "<iso8601>",
  "confidence": "direct | inferred | user_provided | unverified",
  "staleness": "current | stale | unknown",
  "notes": "..."
}
```

---

## Contract Tests (architecture is enforced, not described)

**Hardwiring tests** — fail if source contains absolute user-specific paths, provider model names outside manifests, endpoint URLs outside manifests, or hardcoded ports outside environment config.

**Brain/tool boundary tests** — fail if brain modules import provider SDKs directly, call tools directly, or contain raw endpoint URLs.

**Registry tests** — fail if a manifest lacks an adapter, an active capability points to a missing adapter, two active capabilities share an id, or a routed capability is quarantined/retired/archived.

**Policy tests** — fail if a side-effecting capability lacks policy, or if destructive/financial/public actions can run without confirmation policy.

**Evidence tests** — fail if tool results are not recorded, result objects lack provenance, or stale evidence is treated as current without revalidation.

---

## Implementation Order (cmptrblk)

1. **First pass** — Constitution, registry manifests, lifecycle states, replace fragile hardcoded values
2. **Second pass** — Router, tool bus, normalized result objects, evidence records, adapter migration
3. **Third pass** — Policy gates, agent modes, quarantine/repair, contract tests, `blackzero audit`
4. **Fourth pass** — PlugOps satellites as routable capabilities, locality routing, remote evidence provenance

---

## Definition of Done

BlackZero v2 is complete when:

- A new model can be added without editing brain logic.
- A new tool can be added with a manifest and adapter.
- A broken endpoint is caught by validation before runtime.
- A moved path is repaired through registry/config, not scattered code edits.
- A quarantined model is preserved but excluded from normal routing.
- A side-effecting action cannot run without policy.
- A final answer can show what evidence supports its important claims.
- A developer can run one audit command and see architectural drift.
- PlugOps satellites can be represented as routable capabilities.
- The template makes the right architecture easier than the wrong one.
