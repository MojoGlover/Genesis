# Engineer Swarm Architecture

**Status:** Concept — not yet built. Template to be created alongside BlackZero.
**Date captured:** 2026-05-07

---

## Core Principle

Zee (Engineer0) is the brain of the swarm. She does not delegate intelligence —
she delegates execution. Every sub-engineer is an extension of her, not a peer.

---

## What Lives With Zee

- All memory (conversation history, task history, SQLite)
- All learned skills and knowledge
- The embedding store that defines each sub-engineer's identity and specialization
- Orchestration — she decides who does what

Sub-engineers do not carry their own memory. They borrow Zee's context for the
duration of a task and return results to her. When they go away, nothing is lost.

---

## Sub-Engineer Types

### Named Engineers (fixed identity)

These have embeddings stored in Zee that make them who they are. Their
personality, specialization, and skills are embedded — not configured.

| Name | Identity |
|------|----------|
| EngineerV (Vee) | Fixed — defined by embeddings in Zee |
| EngineerX (X) | Fixed — defined by embeddings in Zee |

### Generic Engineers (assignable)

Engineers 1–4 and 6–9. No fixed identity. When spun up, Zee assigns:
- A mission (what they're doing)
- An LLM (what model they think with)

They are disposable. Two generic engineers doing different tasks are different
agents by assignment, not by nature. When the task ends, they can be reassigned
or shut down.

---

## What Makes a Sub-Engineer Different From a Normal Agent

| Normal Agent (BlackZero-stamped) | Sub-Engineer |
|----------------------------------|-------------|
| Own memory, own identity | Identity lives in Zee's embeddings |
| Registered in PlugOps grid as peer | Spun up by Zee, reports to Zee |
| Own mission file | Mission assigned at spin-up (generics) or embedded (named) |
| Own LLM config | LLM assigned at spin-up (generics) |
| Persists indefinitely | Exists for the duration of a task or session |

---

## The Template

A new template will be created alongside BlackZero:

```
GENESIS/EngineerUnit/   ← self-contained engineer template
```

This template is NOT stamped from BlackZero. It is its own thing. Key differences
from BlackZero:

- No standalone memory system — memory calls route to Zee
- No independent mission file — mission injected at boot
- No fixed LLM — model assigned at spin-up
- Lightweight: optimized for fast spin-up and task execution
- Identity slot: accepts embedding context from Zee at boot (named engineers only)

---

## Open Questions (to resolve when building)

- How does Zee pass embedding context to a named engineer at spin-up?
- Do generic engineers connect to PlugOps as registered agents or stay internal to Zee?
- What is the communication protocol — direct API call, PlugOps routing, or shared memory?
- How does Zee know a sub-engineer has finished and collect the result?
- Can multiple generic engineers run concurrently on different tasks?

---

## What NOT To Build Yet

Do not build this now. Capture the concept, create the template structure when
Darnie is ready to start. Do not try to fit this into BlackZero — it is a
separate lineage.
