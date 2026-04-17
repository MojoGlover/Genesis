"""
registry.py — Tool registry for Engineer0's ReAct loop.

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
import re
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


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
{"tool": "shell", "params": {"command": "ls -la /tmp", "cwd": "/Users/darnieglover/ai/cmptrblk", "timeout": 30}}
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
{"tool": "git_status", "params": {"repo_path": "/Users/darnieglover/ai/cmptrblk/Engineer0"}}
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

### Rules
- Use the minimum number of tool calls needed.
- Prefer read_file before editing — always know what you're changing.
- Use patch_file for small targeted edits; write_file for full rewrites.
- Always git_fetch before git_push.
- If a tool fails, diagnose before retrying.
- If you hit max iterations without finishing, summarize what you did and what remains.
"""


# ── Registry ──────────────────────────────────────────────────────────────────

def build_executor() -> Callable[[str, dict], str]:
    """
    Build and return the tool executor function.
    Called once at agent boot. Returns a closure over all tool modules.
    """
    from agent.tools import shell, files, git_tool, python_repl, web

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

            else:
                return f"Unknown tool: '{tool_name}'. Check TOOLS section for available tools."

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
    # Try fenced code block first
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if block_match:
        try:
            data = json.loads(block_match.group(1))
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass

    # Try bare JSON object with "tool" key
    bare_match = re.search(r'\{[^{}]*"tool"\s*:[^{}]*\}', text, re.DOTALL)
    if bare_match:
        try:
            data = json.loads(bare_match.group(0))
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass

    return None
