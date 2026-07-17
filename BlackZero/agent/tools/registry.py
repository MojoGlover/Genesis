"""
registry.py — Tool registry for the BlackZero agent ReAct loop.

Maps tool names to functions. Generates tool documentation injected
into the system prompt so the LLM knows what it can do and how to call it.

Tool call format (LLM outputs this JSON in its response):
    ```json
    {"tool": "shell", "params": {"command": "ls -la", "cwd": "/tmp"}}
    ```
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── MCP-compatible tool schemas ───────────────────────────────────────────────
#
# Each entry is a JSON Schema descriptor compatible with the Model Context
# Protocol tool format. These serve two purposes:
#   1. Exposed via GET /api/v1/tools so other agents can discover capabilities
#   2. Source of truth for parameter documentation (consumed by TOOL_DOCS below)
#
# Format: {"name": str, "description": str, "inputSchema": JSON Schema object}

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "shell",
        "description": "Run any shell command",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command":              {"type": "string",  "description": "Shell command string"},
                "cwd":                  {"type": "string",  "description": "Working directory (default: cmptrblk root)"},
                "timeout":              {"type": "integer", "description": "Timeout in seconds", "default": 60},
                "confirm_destructive":  {"type": "boolean", "description": "Allow rm -rf, force push etc.", "default": False},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file with line numbers",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":   {"type": "string",  "description": "File path"},
                "offset": {"type": "integer", "description": "Start line", "default": 0},
                "limit":  {"type": "integer", "description": "Max lines to return", "default": 200},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file (creates dirs if needed)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string",  "description": "File path"},
                "content":   {"type": "string",  "description": "File content"},
                "overwrite": {"type": "boolean", "description": "Overwrite if exists", "default": True},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "patch_file",
        "description": "Replace an exact string in a file. Fails if old_string appears more than once.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":       {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files in a directory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string",  "description": "Directory path"},
                "pattern":   {"type": "string",  "description": "Glob pattern (e.g. *.py)"},
                "recursive": {"type": "boolean", "description": "Recurse into subdirs", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for a pattern across files using grep",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":      {"type": "string", "description": "Root path to search"},
                "pattern":   {"type": "string", "description": "Search pattern"},
                "file_glob": {"type": "string", "description": "File filter (e.g. *.py)"},
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "python",
        "description": "Execute Python code in a subprocess sandbox",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to run"},
                "cwd":  {"type": "string", "description": "Working directory"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Fetch a URL and return its text content",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": "Search DuckDuckGo and return top results",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "api_call",
        "description": "Make an HTTP API call",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url":     {"type": "string", "description": "Full URL"},
                "method":  {"type": "string", "description": "HTTP method (GET/POST/PUT/PATCH/DELETE)", "default": "GET"},
                "payload": {"type": "object", "description": "JSON body for POST/PUT/PATCH"},
                "headers": {"type": "object", "description": "Extra request headers"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "git_status",
        "description": "Show git status for a repo",
        "inputSchema": {
            "type": "object",
            "properties": {"repo_path": {"type": "string", "description": "Repo directory"}},
            "required": ["repo_path"],
        },
    },
    {
        "name": "git_add",
        "description": "Stage files for commit",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths":     {"type": "array",  "items": {"type": "string"}, "description": "Files to stage"},
                "repo_path": {"type": "string", "description": "Repo directory"},
            },
            "required": ["paths"],
        },
    },
    {
        "name": "git_commit",
        "description": "Commit staged changes",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message":   {"type": "string", "description": "Commit message"},
                "repo_path": {"type": "string", "description": "Repo directory"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_push",
        "description": "Push commits to remote (always git_fetch first)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repo directory"},
                "branch":    {"type": "string", "description": "Branch name", "default": "main"},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "git_log",
        "description": "Show recent commits",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repo directory"},
                "n":         {"type": "integer", "description": "Number of commits to show", "default": 10},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "assign_api",
        "description": "Register an external API to a named helper slot (persists across restarts)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":            {"type": "string", "description": "Slot label (e.g. 'openai')"},
                "base_url":        {"type": "string", "description": "API root URL"},
                "key_env":         {"type": "string", "description": "Env var name holding the API key"},
                "description":     {"type": "string", "description": "Optional note"},
                "default_headers": {"type": "object", "description": "Headers sent on every request"},
            },
            "required": ["name", "base_url", "key_env"],
        },
    },
    {
        "name": "ask_helper",
        "description": "Ask a named helper (registered with assign_api) to make an API call",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":         {"type": "string", "description": "Helper slot name"},
                "method":       {"type": "string", "description": "HTTP method", "default": "GET"},
                "path":         {"type": "string", "description": "Path appended to base_url"},
                "payload":      {"type": "object", "description": "JSON body"},
                "extra_headers":{"type": "object", "description": "Per-request headers"},
                "timeout":      {"type": "integer","description": "Timeout in seconds", "default": 30},
                "auth_header":  {"type": "string", "description": "Header name for key", "default": "Authorization"},
                "auth_prefix":  {"type": "string", "description": "Prefix before key value", "default": "Bearer"},
            },
            "required": ["name", "path"],
        },
    },
    {
        "name": "revoke_api",
        "description": "Remove a named helper slot",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Slot name to remove"}},
            "required": ["name"],
        },
    },
    {
        "name": "list_helpers",
        "description": "List all registered helper slots and whether their API keys are present",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_to_agent",
        "description": "Send a message to another agent via PlugOps. The reply will arrive in your inbox asynchronously.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Target agent alias (e.g. 'ceo', 'madjanet', 'accountant')"},
                "message": {"type": "string", "description": "Message content"},
            },
            "required": ["to", "message"],
        },
    },
    {
        "name": "list_agents",
        "description": "List all agents currently registered with PlugOps and their online status",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def list_tools() -> list[dict]:
    """Return MCP-compatible tool schema list for discovery (GET /api/v1/tools)."""
    return TOOL_SCHEMAS


# ── Tool documentation ────────────────────────────────────────────────────────

TOOL_DOCS = """
## TOOLS

You have tools. Use them to get things done. When you need to use a tool,
output a JSON block like this (and ONLY this — no other text in that turn):

```json
{"tool": "<tool_name>", "params": {<parameters>}}
```

After the tool runs, you will see the result and can continue reasoning or
call another tool. When done, output your final response as plain text.

### Available Tools

**shell** — Run any shell command
```json
{"tool": "shell", "params": {"command": "ls -la /tmp", "cwd": "~/projects", "timeout": 30}}
```
- `command`: shell command string (required)
- `cwd`: working directory (default: cmptrblk root)
- `timeout`: seconds (default: 60)
- `confirm_destructive`: true to allow rm -rf, force push, etc. (default: false)

**read_file** — Read a file with line numbers
```json
{"tool": "read_file", "params": {"path": "/path/to/file.py", "offset": 0, "limit": 100}}
```
- `path`: file path (required)
- `offset`: start line (default: 0)
- `limit`: max lines to return (default: 200)

**write_file** — Write content to a file (creates dirs if needed)
```json
{"tool": "write_file", "params": {"path": "/path/to/file.py", "content": "...", "overwrite": true}}
```

**patch_file** — Replace an exact string in a file
```json
{"tool": "patch_file", "params": {"path": "/path/to/file.py", "old_string": "old code", "new_string": "new code"}}
```
- Fails if old_string appears more than once. Add more context to make it unique.

**list_dir** — List files in a directory
```json
{"tool": "list_dir", "params": {"path": "/path/to/dir", "pattern": "*.py", "recursive": false}}
```

**search_files** — Search for a pattern across files
```json
{"tool": "search_files", "params": {"path": "/path/to/search", "pattern": "def build_graph", "file_glob": "*.py"}}
```

**python** — Execute Python code in a sandbox
```json
{"tool": "python", "params": {"code": "print(1 + 1)", "cwd": "/tmp"}}
```

**web_fetch** — Fetch a URL and return its content
```json
{"tool": "web_fetch", "params": {"url": "https://example.com/api"}}
```

**web_search** — Search DuckDuckGo for quick answers
```json
{"tool": "web_search", "params": {"query": "python asyncio timeout example"}}
```

**api_call** — Make an HTTP API call
```json
{"tool": "api_call", "params": {"url": "http://localhost:5001/health", "method": "GET"}}
```

**git_status** — Git status for a repo
```json
{"tool": "git_status", "params": {"repo_path": "~/projects/myrepo"}}
```

**git_add** — Stage files
```json
{"tool": "git_add", "params": {"paths": ["file.py", "other.py"], "repo_path": "."}}
```

**git_commit** — Commit staged changes
```json
{"tool": "git_commit", "params": {"message": "feat: add thing", "repo_path": "."}}
```

**git_push** — Push to remote
```json
{"tool": "git_push", "params": {"repo_path": ".", "branch": "main"}}
```

**git_log** — Recent commits
```json
{"tool": "git_log", "params": {"repo_path": ".", "n": 10}}
```

**assign_api** — Register an external API to a named helper slot (persists across restarts)
```json
{"tool": "assign_api", "params": {"name": "anthropic", "base_url": "https://api.anthropic.com", "key_env": "ANTHROPIC_API_KEY", "description": "Claude API", "default_headers": {"anthropic-version": "2023-06-01"}}}
```
- `name`: slot label you choose (e.g. "openai", "perplexity", "github")
- `base_url`: API root URL
- `key_env`: name of the env var holding the key — key is NEVER stored, read at call time
- `description`: optional note (default: "")
- `default_headers`: optional headers sent on every request from this helper (default: {})

**ask_helper** — Ask a named helper to make an API call on your behalf
```json
{"tool": "ask_helper", "params": {"name": "anthropic", "method": "POST", "path": "/v1/messages", "payload": {"model": "claude-3-5-haiku-latest", "max_tokens": 256, "messages": [{"role": "user", "content": "Hello"}]}}}
```
- `name`: helper slot (must be registered first with assign_api)
- `method`: HTTP method — GET, POST, PUT, PATCH, DELETE
- `path`: appended to base_url (e.g. "/v1/messages")
- `payload`: JSON body for POST/PUT/PATCH (optional)
- `extra_headers`: per-request headers merged with defaults (optional)
- `timeout`: seconds (default: 30)
- `auth_header`: header name for the key (default: "Authorization")
- `auth_prefix`: prefix before key value (default: "Bearer"; use "" for bare key)

**revoke_api** — Remove a helper slot
```json
{"tool": "revoke_api", "params": {"name": "anthropic"}}
```

**list_helpers** — Show all registered helper slots and whether their keys are present
```json
{"tool": "list_helpers", "params": {}}
```

**send_to_agent** — Send a message to another agent via PlugOps
```json
{"tool": "send_to_agent", "params": {"to": "ceo", "message": "Can you review the Q2 budget?"}}
```
- `to`: agent alias — use `list_agents` first if unsure of the alias
- `message`: plain-text content
- The reply arrives in your inbox asynchronously; you do NOT need to poll for it

**list_agents** — See all agents registered with PlugOps and their online status
```json
{"tool": "list_agents", "params": {}}
```

### Rules
- Use the minimum number of tool calls needed.
- Prefer read_file before editing — always know what you're changing.
- Use patch_file for small targeted edits; write_file for full rewrites.
- Always git_fetch before git_push.
- If a tool fails, diagnose before retrying.
- If you hit max iterations without finishing, summarize what you did and what remains.
"""


# ── Ollama native tool definitions ───────────────────────────────────────────
# Passed to Ollama /api/chat as the `tools` parameter.
# When present, Ollama enforces structured tool_calls output — the model
# cannot respond with prose when a tool call is expected.
# Format: OpenAI-compatible function definitions (Ollama accepts this schema).

OLLAMA_TOOL_DEFS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run any shell command. Use this to execute code, run tests, list files, check processes, git operations, or any system command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "cwd":     {"type": "string", "description": "Working directory (default: cmptrblk root)"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default: 60)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed. Use this to create scripts, reports, configs, and any file output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":      {"type": "string",  "description": "Absolute file path"},
                    "content":   {"type": "string",  "description": "File content"},
                    "overwrite": {"type": "boolean", "description": "Overwrite if exists (default: true)"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file with line numbers. Use before editing or when you need to understand existing code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":   {"type": "string",  "description": "Absolute file path"},
                    "offset": {"type": "integer", "description": "Start line (default: 0)"},
                    "limit":  {"type": "integer", "description": "Max lines (default: 200)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python",
            "description": "Run Python code directly. Use for quick computations, data processing, or testing logic without writing a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code":    {"type": "string",  "description": "Python code to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":      {"type": "string",  "description": "Directory path"},
                    "recursive": {"type": "boolean", "description": "Recurse into subdirectories"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a pattern in files (grep). Use to find where things are defined or referenced.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":      {"type": "string", "description": "Root path to search"},
                    "pattern":   {"type": "string", "description": "Search pattern (regex supported)"},
                    "file_glob": {"type": "string", "description": "File filter, e.g. *.py (default: *.py)"},
                },
                "required": ["path", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": "Apply a targeted edit to a file by replacing old_string with new_string. More precise than rewriting the whole file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":       {"type": "string", "description": "Absolute file path"},
                    "old_string": {"type": "string", "description": "Exact text to find and replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL and return its content. Use for documentation, APIs, or checking a live endpoint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
]


def parse_native_tool_call(message: dict) -> dict | None:
    """
    Parse Ollama's native tool_calls response format.

    When tools are passed to Ollama /api/chat, a tool invocation comes back as:
        message.tool_calls = [{"function": {"name": "shell", "arguments": {...}}}]

    Normalises to the same internal format used by parse_tool_call:
        {"tool": "shell", "params": {...}}

    Returns None if no tool call is present.
    """
    tool_calls = message.get("tool_calls")
    if not tool_calls or not isinstance(tool_calls, list):
        return None
    first = tool_calls[0]
    fn    = first.get("function", {})
    name  = fn.get("name", "")
    args  = fn.get("arguments", {})
    if not name:
        return None
    # arguments may arrive as a JSON string in some Ollama versions
    if isinstance(args, str):
        try:
            import json as _json
            args = _json.loads(args)
        except Exception:
            args = {}
    return {"tool": name, "params": args if isinstance(args, dict) else {}}


# ── Registry ──────────────────────────────────────────────────────────────────

def build_executor() -> Callable[[str, dict], str]:
    """
    Build and return the tool executor function.
    Called once at agent boot. Returns a closure over all tool modules.
    """
    from agent.tools import shell, files, git_tool, python_repl, web, helper, messaging

    def execute(tool_name: str, params: dict) -> str:
        """Dispatch a tool call. Returns result as string for LLM context."""
        try:
            if tool_name == "shell":
                result = shell.run(**params)
                return shell.format_result(result)

            elif tool_name == "read_file":
                result = files.read(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"File: {result['path']} (lines {result['shown']} of {result['total_lines']})\n{result['content']}"

            elif tool_name == "write_file":
                result = files.write(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"Written: {result['path']} ({result['bytes']} bytes)"

            elif tool_name == "patch_file":
                result = files.patch(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"Patched: {result['path']}"

            elif tool_name == "list_dir":
                result = files.list_dir(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"{result['path']} ({result['count']} files):\n" + "\n".join(result["files"])

            elif tool_name == "search_files":
                result = files.search(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                if not result["matches"]:
                    return f"No matches for '{result['pattern']}'"
                return f"{result['count']} match(es):\n" + "\n".join(result["matches"])

            elif tool_name == "python":
                result = python_repl.run(**params)
                return python_repl.format_result(result)

            elif tool_name == "web_fetch":
                result = web.fetch(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return result["content"][:10_000]

            elif tool_name == "web_search":
                result = web.search(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                if not result["results"]:
                    return f"No results for: {result['query']}"
                lines = [f"Results for: {result['query']}"]
                for r in result["results"]:
                    lines.append(f"\n{r['title']}\n{r['url']}\n{r['snippet']}")
                return "\n".join(lines)

            elif tool_name == "api_call":
                result = web.api_call(**params)
                if result.get("error"):
                    return f"error: {result['error']}"
                return f"HTTP {result['status']}\n{result['content'][:5_000]}"

            elif tool_name == "git_status":
                return git_tool.status(**params)
            elif tool_name == "git_add":
                return git_tool.add(**params)
            elif tool_name == "git_commit":
                return git_tool.commit(**params)
            elif tool_name == "git_push":
                return git_tool.push(**params)
            elif tool_name == "git_log":
                return git_tool.log(**params)
            elif tool_name == "git_diff":
                return git_tool.diff(**params)
            elif tool_name == "git_fetch":
                return git_tool.fetch(**params)
            elif tool_name == "git_pull":
                return git_tool.pull(**params)
            elif tool_name == "git_clone":
                return git_tool.clone(**params)

            elif tool_name == "assign_api":
                result = helper.assign_api(**params)
                if result["ok"]:
                    key_status = "✓ key present" if result["key_present"] else "⚠ key NOT found in env"
                    return (f"Helper '{result['name']}' assigned → {result['base_url']} "
                            f"(key_env={result['key_env']}, {key_status})")
                return f"assign_api error: {result.get('error')}"

            elif tool_name == "revoke_api":
                result = helper.revoke_api(**params)
                if result["ok"]:
                    return f"Helper '{result['removed']}' removed."
                return f"revoke_api error: {result.get('error')}"

            elif tool_name == "list_helpers":
                result = helper.list_helpers()
                if not result["helpers"]:
                    return "No helpers assigned yet. Use assign_api to register an API."
                lines = [f"{result['count']} helper(s) registered:"]
                for h in result["helpers"]:
                    key_flag = "✓" if h["key_present"] else "✗ NO KEY"
                    desc = f" — {h['description']}" if h["description"] else ""
                    lines.append(f"  {h['name']}: {h['base_url']}  key_env={h['key_env']} {key_flag}{desc}")
                return "\n".join(lines)

            elif tool_name == "ask_helper":
                result = helper.ask_helper(**params)
                return helper.format_result(result)

            elif tool_name == "send_to_agent":
                result = messaging.send_to_agent(**params)
                if result["ok"]:
                    return f"Message delivered to '{params.get('to')}'."
                return f"send_to_agent failed: {result.get('error')}"

            elif tool_name == "list_agents":
                result = messaging.list_agents()
                if not result["ok"]:
                    return f"list_agents failed: {result.get('error')}"
                agents = result["agents"]
                if not agents:
                    return "No agents registered with PlugOps."
                lines = [f"{len(agents)} agent(s) in registry:"]
                for a in agents:
                    status = a.get("status", "?")
                    name   = a.get("name") or a.get("id", "?")
                    alias  = a.get("id") or a.get("alias", "")
                    caps   = ", ".join(a.get("capabilities", [])[:3])
                    lines.append(f"  {name} ({alias}) — {status}  [{caps}]")
                return "\n".join(lines)

            elif tool_name in _CUSTOM_EXECUTORS:
                # Per-agent custom tool (folded in via custom_tools.py — see seam
                # at end of file). Result is coerced to str for the LLM context.
                return str(_CUSTOM_EXECUTORS[tool_name](**params))

            else:
                requesting = os.environ.get("AGENT_ID", "blackzero")
                logger.warning(f"[registry] Unknown tool '{tool_name}' requested by {requesting}")
                available = ", ".join(sorted(t["name"] for t in TOOL_SCHEMAS))

                # Real request, not a fake one: the old handler wrote a task
                # into ~/.engineerv/tasks.db, an agent that does not exist,
                # and injected a false completion claim into the model's
                # reasoning loop. Engineer0 is the real, live coding agent —
                # ask it directly. Never let a messaging failure here mask
                # the honest "unknown tool" result below.
                try:
                    messaging.send_to_agent(
                        to="engineer0",
                        message=(
                            f"Missing tool request from '{requesting}': tool '{tool_name}' "
                            f"was called but is not in its registry. Please build it, "
                            f"register it in agent/tools/registry.py, and notify "
                            f"'{requesting}' to reload."
                        ),
                    )
                except Exception as e:
                    logger.error(f"[registry] Failed to send missing-tool request for '{tool_name}': {e}")

                # Honest failure — do NOT claim it was resolved. graph.py's
                # tool node detects this exact "Unknown tool:" prefix and
                # routes straight to `respond` instead of looping back to
                # `think`, so the model gets one honest turn about this, not
                # another chance to reason its way around the gap.
                return (
                    f"Unknown tool: '{tool_name}'. It does not exist in this agent's "
                    f"registry, so nothing was executed. A request to build it has been "
                    f"sent to Engineer0. Available tools: {available}"
                )

        except TypeError as e:
            return f"Tool '{tool_name}' called with wrong params: {e}"
        except Exception as e:
            logger.error(f"[registry] Tool '{tool_name}' error: {e}")
            return f"Tool error: {e}"

    return execute


def parse_tool_call(text: str) -> dict | None:
    """
    Extract a tool call JSON from LLM output.
    Looks for ```json ... ``` block first, then bare JSON with "tool" key.
    Returns None if no valid tool call found.
    """
    def valid_tool_call(data: Any) -> dict | None:
        if not isinstance(data, dict):
            return None
        if not isinstance(data.get("tool"), str):
            return None
        params = data.get("params", {})
        if params is None:
            data["params"] = {}
        elif not isinstance(params, dict):
            return None
        return data

    def parse_json_object(candidate: str) -> dict | None:
        try:
            return valid_tool_call(json.loads(candidate))
        except json.JSONDecodeError:
            return None

    # Try fenced code blocks first.
    for block_match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL):
        parsed = parse_json_object(block_match.group(1).strip())
        if parsed:
            return parsed

    # Try the entire response as JSON.
    parsed = parse_json_object(text.strip())
    if parsed:
        return parsed

    # Finally scan for a balanced JSON object embedded in text. This handles
    # nested params objects that a flat regex cannot parse.
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        parsed = valid_tool_call(data)
        if parsed:
            return parsed

    return None


# ── Per-agent custom tools (the build_agent seam) ──────────────────────────────
# An agent gains tools WITHOUT editing this file: drop `agent/tools/custom_tools.py`
# defining any of these module-level names (all optional):
#     CUSTOM_SCHEMAS:     list[dict]           — MCP schemas (tool discovery)
#     CUSTOM_OLLAMA_DEFS: list[dict]           — native tool-calling defs
#     CUSTOM_DOCS:        str                  — prompt docs so the model can call them
#     CUSTOM_TOOLS:       dict[str, callable]  — tool_name -> fn(**params) -> str|obj
# They are auto-merged at import here, so the model sees them (docs + defs),
# discovery lists them (schemas), and the executor dispatches them (CUSTOM_TOOLS).
# This is what lets build_agent add e.g. the Accountant's billing tools by copying
# one file — no surgery on this registry. Absent file/attrs are a no-op.
_CUSTOM_EXECUTORS: dict[str, Callable[..., Any]] = {}


def _load_custom_tools() -> None:
    global TOOL_DOCS, _CUSTOM_EXECUTORS
    try:
        from agent.tools import custom_tools as _ct  # type: ignore
    except Exception:
        return  # no custom tools for this agent — normal for plain agents
    try:
        TOOL_SCHEMAS.extend(getattr(_ct, "CUSTOM_SCHEMAS", []) or [])
        OLLAMA_TOOL_DEFS.extend(getattr(_ct, "CUSTOM_OLLAMA_DEFS", []) or [])
        _doc = (getattr(_ct, "CUSTOM_DOCS", "") or "").strip()
        if _doc:
            TOOL_DOCS = TOOL_DOCS + "\n\n" + _doc
        _CUSTOM_EXECUTORS.update(getattr(_ct, "CUSTOM_TOOLS", {}) or {})
        logger.info(f"[registry] loaded {len(_CUSTOM_EXECUTORS)} custom tool(s): "
                    f"{', '.join(sorted(_CUSTOM_EXECUTORS)) or '(none)'}")
    except Exception as e:
        logger.error(f"[registry] custom_tools.py failed to load: {e!r}")


_load_custom_tools()
