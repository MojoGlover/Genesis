# Tool Bus — Remote Tool Execution via PlugOps

**Status:** Implemented 2026-05-07  
**Problem:** Tools are hardcoded local to the agent's host. If Engineer0 moves plugs or runs in a hostless container, she cannot execute any tools — she can chat but that's it.  
**Solution:** Expose tools via HTTP on the plug that has them. PlugOps routes tool requests to the right executor via grid resolution.

---

## The Problem

Engineer0's tools (`shell`, `read_file`, `write_file`, etc.) run as local subprocesses on whatever host she's deployed to. The tool executor is a closure built at boot from local Python modules. This means:

- Move Engineer0 to a locked container → no shell access → no tools
- Move to a plug without her codebase → import fails at boot
- Other agents want to use tools → they have to call Engineer0 directly, knowing her URL

Tools are not portable. The agent and her tools are fused at deploy time.

---

## The Fix

Two endpoints. One on Engineer0, one on PlugOps.

```
Agent                PlugOps                    Engineer0 (tool host)
  │                     │                              │
  │── POST /api/v1/ ───▶│                              │
  │   tools/execute     │── POST /api/tools/execute ──▶│
  │   {tool, params,    │   (grid-resolved URL)        │── executes locally
  │    executor}        │                              │
  │                     │◀─ {result, ok} ─────────────│
  │◀─ {result, ok} ────│                              │
```

### Engineer0: `POST /api/tools/execute`

Exposes her full tool set over HTTP. Any agent or PlugOps can call it.

- Request: `{"tool": "shell", "params": {"command": "ls"}}`
- Response: `{"result": "file1.py\nfile2.py", "ok": true}`
- Auth: `X-Agent-Id` header required (any registered agent can call)

### PlugOps: `POST /api/v1/tools/execute`

Proxy endpoint. Resolves the executor via grid, forwards the request, returns the result. Callers never need to know where the tool host lives.

- Request: `{"tool": "shell", "params": {...}, "executor": "engineer0"}`
- `executor` defaults to `"engineer0"` — she is the default tool host
- PlugOps does `grid.resolve("engineer0", "/api/tools/execute")` → forwards
- Response: same as Engineer0's response, plus `{"executor_url": "..."}`

---

## What This Enables

| Before | After |
|--------|-------|
| CEO agent wants to run a shell command | CEO calls PlugOps `/api/v1/tools/execute` — PlugOps routes to Engineer0 |
| Engineer0 deployed to a hostless container | She calls PlugOps tool proxy → tools run on plugfoe's Engineer0 instance |
| New plug with no tools | Register an agent there, point `executor` to plugfoe |
| Engineer0 moves to RunPod | GridResolver updates her URL — all tool calls follow automatically |

---

## What It Does NOT Do (Yet)

- Tool authorization per agent (any registered agent can call any tool) — policy gate hooks will handle this when PolicyGate is built
- Capability-based routing (route `shell` to plugfoe, `gpu_inference` to RunPod) — add a `capability_registry` to PlugOps when needed
- Engineer0 routing her OWN tool calls through PlugOps — she still executes locally for now (no roundtrip overhead, no circular dependency). Remote routing only matters when she moves to a toolless environment.

---

## Files Changed

- `Engineer0/agent/api/server.py` — added `POST /api/tools/execute`
- `PlugOps/plugops/api/server.py` — added `POST /api/v1/tools/execute`
- `GENESIS/specs/TOOL_BUS.md` — this document
