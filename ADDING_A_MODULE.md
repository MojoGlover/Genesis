# Adding a Module to GENESIS

> **This is the canonical guide.** The older `ADDING_A_TOOL.md` describes a legacy
> pattern (pip-installable packages). This document describes the live standard.

---

## How the Module System Works

GENESIS auto-discovers every directory under `modules/` that contains a
`module.py` with a class named `Module` subclassing `ModuleBase`.

**No configuration file is touched. No `app.py` edits are needed. Drop in the
directory and restart.**

```
startup sequence
────────────────
app.py lifespan
  └─ ModuleRegistry.mount_all(app)
       ├─ discover()          # scan modules/ lexicographically
       │    └─ for each dir → import module.py → Module()
       ├─ app.include_router(module.router)   # mount HTTP routes
       ├─ validate tools in ToolRegistry
       ├─ register + start agents
       ├─ await module.on_startup()
       └─ expose /modules  and  /modules/{name}/health
```

---

## Step-by-Step: Create a New Module

### 1 — Create the directory

```
modules/
└── <your_module>/
    ├── module.json   ← manifest (required by registry policy)
    └── module.py     ← class Module(ModuleBase)
```

Replace `<your_module>` with a lowercase slug: `vision`, `scheduler`, `tax`, etc.

---

### 2 — Write the manifest (`module.json`)

```json
{
  "name":        "flex.<your_module>",
  "version":     "1.0.0",
  "description": "One sentence — what this module does.",
  "entry":       "module.py",
  "permissions": ["read:packages"],
  "tags":        ["<your_module>", "flex"]
}
```

**Known permissions** (declare only what you need):

| Permission         | Meaning                        |
|--------------------|--------------------------------|
| `read:packages`    | Read installed Python packages |
| `write:packages`   | Modify packages                |
| `read:filesystem`  | Read files from disk           |
| `write:filesystem` | Write files to disk            |
| `read:network`     | Outbound HTTP/socket reads     |
| `write:network`    | Send over network              |
| `read:memory`      | Inspect in-process state       |
| `write:memory`     | Mutate in-process state        |
| `execute:process`  | Spawn subprocesses             |

Any unknown permission causes mount failure. Declare accurately.

---

### 3 — Write `module.py`

```python
# modules/<your_module>/module.py
from fastapi import APIRouter
from pydantic import BaseModel
from core.modules.base import ModuleBase


# ── Pydantic I/O models (required — no raw dict at API boundaries) ────────────

class HelloRequest(BaseModel):
    name: str

class HelloResponse(BaseModel):
    greeting: str
    module:   str


# ── Module ────────────────────────────────────────────────────────────────────

class Module(ModuleBase):

    @property
    def name(self) -> str:        return "hello"
    @property
    def version(self) -> str:     return "1.0.0"
    @property
    def description(self) -> str: return "Greets users."

    @property
    def router(self) -> APIRouter:
        r = APIRouter(prefix="/hello", tags=["hello"])

        @r.post("/greet", response_model=HelloResponse)
        async def greet(body: HelloRequest) -> HelloResponse:
            return HelloResponse(greeting=f"Hello, {body.name}!", module=self.name)

        return r

    def health(self) -> dict:
        return {"status": "ok", "module": self.name, "version": self.version}
```

That is a complete, working module.

---

### 4 — Restart GENESIS

```bash
cd ~/ai/GENESIS
python app.py
```

Your routes are live at `POST /hello/greet`.
Your module appears at `GET /modules` and `GET /modules/hello/health`.

---

## Rules You Must Follow

These are enforced by the module registry policy (`genesis/policies/`).

| Rule | Why |
|------|-----|
| **Zero side effects on import** | No network calls, file writes, thread spawning, or print/logging at module scope. Put everything in `on_startup()`. |
| **Pydantic I/O** | Every endpoint body and response must use a Pydantic model. No `dict`, no `Any` at API boundaries. |
| **Lazy imports** | Heavy dependencies (ML models, DB drivers, large SDKs) must be imported inside `on_startup()` or on first use — not at the top of the file. |
| **Unique name** | `self.name` must be unique across all modules. Duplicates cause mount failure. |
| **Health method** | Must return at minimum `{"status": "ok"|"degraded"|"error", "module": ..., "version": ...}`. |

---

## What `core/` Gives You Free

Your `module.py` can import any of these — no setup required:

```python
# Providers (Ollama / OpenAI / Claude / Gemini)
from core.providers.ollama import OllamaProvider

# Message bus (pub/sub across modules)
from core.messaging.bus import get_message_bus

# Storage (SQLite + Qdrant vector store)
from core.storage.sqlite import get_db
from core.storage.qdrant import get_vector_store

# Tool registry (LLM-callable tools)
from agents.tools.tool_registry import get_registry as get_tool_registry

# Agent base class
from core.monitoring.registry import get_agent_registry
```

---

## Lifecycle Hooks

Override these in your `Module` when you need async setup/teardown:

```python
async def on_startup(self) -> None:
    # Called AFTER router is mounted and agents are started
    # Safe to do: open DB connections, load models, warm caches
    self._db = await open_connection(...)

async def on_shutdown(self) -> None:
    # Called BEFORE process exits
    # Clean up connections, flush buffers
    if hasattr(self, "_db"):
        await self._db.close()
```

---

## Adding Tools (LLM-callable functions)

```python
from agents.tools.tool_registry import register_tool

@register_tool
def my_tool(query: str) -> str:
    """Docstring = description shown to the LLM."""
    return do_something(query)

class Module(ModuleBase):
    @property
    def tools(self):
        return [my_tool]   # registry validates these exist
```

---

## Adding Agents

```python
from core.agent_base import AgentBase   # or your AgentBase subclass

class MyWorker(AgentBase):
    ...

class Module(ModuleBase):
    def __init__(self):
        self._worker = MyWorker()

    @property
    def agents(self):
        return [self._worker]   # registry calls .start() / .stop()
```

---

## Reference Example: `modules/tax/`

The tax module is the canonical real-world example in this codebase.

```
modules/tax/
├── module.json              ← manifest
├── module.py                ← class Module(ModuleBase)  ← FastAPI wrapper
└── engine/
    ├── __init__.py
    ├── calculator.py         ← TaxCalculator (stateful, year-switching)
    ├── concepts.py           ← ~20 tax term definitions
    ├── ai_interface.py       ← OpenAI tool definition
    ├── years/
    │   ├── base.py           ← abstract TaxYear
    │   ├── y2024.py          ← 2024 rules
    │   ├── y2025.py          ← 2025 rules
    │   └── y2026.py          ← 2026 TCJA-sunset projections (⚠️)
    └── forms/
        ├── form_1040.py      ← maps TaxResult → Form 1040 line numbers
        └── schedule_c.py     ← Schedule C (self-employment)
```

Routes exposed:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tax/calculate` | Calculate tax for a given year |
| `POST` | `/tax/compare` | Side-by-side comparison across years |
| `GET`  | `/tax/years` | List supported tax years |
| `GET`  | `/tax/concepts` | All defined tax concepts |
| `GET`  | `/tax/concepts/{term}` | Look up a single term |
| `POST` | `/tax/schedule_c` | Run Schedule C (self-employment) |

---

## Module Directory Layout (full)

```
modules/<name>/
├── module.json          required  — manifest, permissions, version
├── module.py            required  — class Module(ModuleBase)
├── <engine or core>/    optional  — business logic lives here
│   └── ...
├── tests/               recommended
│   └── test_<name>.py
└── README.md            recommended
```

Keep business logic out of `module.py`. It is a thin HTTP/lifecycle wrapper.
The engine does the real work. This keeps the module testable independently of
FastAPI.

---

## Testing Your Module

```bash
# Test the engine directly (no server needed)
pytest modules/tax/engine/tests/ -v

# Integration test via live server
python app.py &
curl -X POST http://localhost:7860/tax/calculate \
  -H "Content-Type: application/json" \
  -d '{"year": 2025, "filing_status": "single", "gross_income": 85000}'
```

---

## GENESIS vs Engineer0 — Module Differences

| Concern | GENESIS | Engineer0 |
|---------|---------|-----------|
| Base class | `core.modules.base.ModuleBase` | `engineer0.module_base.FlaskModuleBase` |
| Framework | FastAPI (async) | Flask (sync) |
| Router type | `fastapi.APIRouter` | `flask.Blueprint` |
| Lifecycle hooks | `async def on_startup/on_shutdown` | `def on_startup/on_shutdown` |
| Registry | `core.modules.registry.ModuleRegistry` | `engineer0.module_registry.FlaskModuleRegistry` |
| Module path | `modules/<name>/module.py` | `engineer0/modules/<name>/module.py` |

The pattern is identical — only the framework differs. A module built for
GENESIS can be ported to Engineer0 by swapping the base class and converting
`async` → sync.

---

## Checklist

- [ ] `modules/<name>/module.json` created with all required fields
- [ ] `modules/<name>/module.py` has `class Module(ModuleBase)`
- [ ] `name`, `version`, `description`, `router`, `health()` implemented
- [ ] No side effects at module scope (imports only)
- [ ] All endpoint bodies and responses use Pydantic models
- [ ] Heavy imports deferred to `on_startup()` or first call
- [ ] `health()` returns at minimum `status`, `module`, `version`
- [ ] Module name is unique (check `GET /modules` after restart)
- [ ] Permissions in `module.json` match what the code actually uses
