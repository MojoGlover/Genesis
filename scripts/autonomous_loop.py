#!/usr/bin/env python3
"""
GENESIS Autonomous Loop — Engineer 0 Foundation

Runs every 10 minutes to keep work moving without manual supervision.

Logic:
1. Check if Claude is already running (don't double-invoke)
2. Check task list for pending work
3. If pending → invoke Claude Code CLI to continue
4. If complete → check for user input (iCloud command file)
5. If idle 10+ min → decide what's next based on priorities
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Paths
GENESIS_DIR = Path.home() / "ai/GENESIS"
STATE_FILE = GENESIS_DIR / ".autonomous_state.json"
HEARTBEAT_FILE = GENESIS_DIR / ".session_heartbeat"
PRIORITIES_FILE = GENESIS_DIR / "config/priorities.json"
ROUTING_FILE = GENESIS_DIR / "config/model_routing.json"
ICLOUD_FOLDER = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/genesis-remote"
LOG_FILE = Path("/tmp/genesis-autonomous.log")

# Tool paths
CLAUDE_CLI = "/opt/homebrew/bin/claude"
AIDER_CLI = "/Users/darnieglover/Library/Python/3.11/bin/aider"
CODEX_CLI = "/opt/homebrew/bin/codex"
GEMINI_CLI = "/opt/homebrew/bin/gemini"
OLLAMA_API = "http://localhost:11434/api/generate"

# Local model for loop's own reasoning (never uses cloud credits)
LOCAL_REASONING_MODEL = "llama3.1:70b"
LOCAL_FAST_MODEL = "codellama:13b"

# How long before we consider a session "abandoned" (minutes)
HEARTBEAT_STALE_MINUTES = 10

# Cloud service status tracking
CLOUD_STATUS_FILE = GENESIS_DIR / ".cloud_status.json"

# Task complexity keywords for routing
COMPLEX_KEYWORDS = ["architecture", "design", "multi-file", "refactor entire", "research", "explore", "plan"]
SIMPLE_KEYWORDS = ["lint", "format", "typo", "fix import", "add comment", "rename"]


def log(message: str):
    """Log with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def is_ollama_running() -> bool:
    """Check if Ollama is available locally."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def local_reason(prompt: str, model: str = None) -> str | None:
    """
    Use local Ollama model for reasoning (NO cloud credits used).

    This is for the loop's own decision-making, not for coding tasks.
    Falls back gracefully if Ollama is not running.
    """
    model = model or LOCAL_REASONING_MODEL

    if not is_ollama_running():
        log("Ollama not running - using rule-based fallback")
        return None

    try:
        import urllib.request
        data = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            OLLAMA_API,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            return result.get("response", "").strip()

    except Exception as e:
        log(f"Local reasoning failed: {e}")
        return None


def check_cloud_status() -> dict:
    """
    Check which cloud services are available.

    Returns dict with service availability.
    Uses cached status if recent (avoid hammering APIs).
    """
    # Load cached status
    cached = {}
    if CLOUD_STATUS_FILE.exists():
        try:
            cached = json.loads(CLOUD_STATUS_FILE.read_text())
            last_check = datetime.fromisoformat(cached.get("last_check", "2000-01-01"))
            # Use cache if less than 5 minutes old
            if datetime.now() - last_check < timedelta(minutes=5):
                return cached
        except Exception:
            pass

    status = {
        "last_check": datetime.now().isoformat(),
        "ollama": is_ollama_running(),
        "claude": None,  # Check on first use
        "gemini": None,
        "codex": None,
    }

    # Save status
    try:
        CLOUD_STATUS_FILE.write_text(json.dumps(status, indent=2))
    except Exception:
        pass

    return status


def mark_cloud_unavailable(service: str, reason: str = ""):
    """Mark a cloud service as unavailable (e.g., out of tokens)."""
    status = check_cloud_status()
    status[service] = False
    status[f"{service}_reason"] = reason
    status[f"{service}_failed_at"] = datetime.now().isoformat()

    try:
        CLOUD_STATUS_FILE.write_text(json.dumps(status, indent=2))
    except Exception:
        pass

    log(f"Marked {service} as unavailable: {reason}")


def load_state() -> dict:
    """Load persistent state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "last_activity": None,
        "last_check": None,
        "idle_since": None,
        "tasks_completed": [],
        "current_priority_index": 0,
    }


def save_state(state: dict):
    """Save persistent state."""
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def load_priorities() -> list:
    """Load priority list for autonomous decisions."""
    if PRIORITIES_FILE.exists():
        try:
            data = json.loads(PRIORITIES_FILE.read_text())
            return data.get("priorities", [])
        except Exception:
            pass

    # Default priorities from the roadmap
    return [
        {
            "id": "phase1_monitoring",
            "name": "Build Monitoring Infrastructure",
            "prompt": "Continue building the monitoring infrastructure: health monitor, error logger, alerting system (ntfy.sh), and web dashboard. Check what's already done and proceed with the next component.",
        },
        {
            "id": "phase2_agents",
            "name": "Extract Specialized Agents",
            "prompt": "Continue extracting specialized agents using the AgentBase framework. Priority order: UI Agent, Voice Agent, Scanner Agent, Testing Agent. Check what exists and build the next one.",
        },
        {
            "id": "phase3_mobile",
            "name": "Complete Mobile PWA",
            "prompt": "Continue work on the mobile PWA. Check current state and add any missing features: voice input, GPS tracking, health status display.",
        },
        {
            "id": "phase4_templates",
            "name": "Build Agent Templates",
            "prompt": "Create the agent template system for easy agent creation. Build template files and the create_agent.py script.",
        },
    ]


def is_claude_running() -> bool:
    """Check if Claude Code is already running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "claude"],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def is_session_active() -> bool:
    """
    Check if there's an active user session (not abandoned).

    Returns True if:
    - Claude is running AND heartbeat was updated within HEARTBEAT_STALE_MINUTES

    Returns False if:
    - Claude is not running, OR
    - Claude is running but heartbeat is stale (user walked away)
    """
    if not is_claude_running():
        return False

    # Check heartbeat file
    if not HEARTBEAT_FILE.exists():
        # No heartbeat file = can't tell, assume stale
        return False

    try:
        data = json.loads(HEARTBEAT_FILE.read_text())
        last_activity = data.get("last_activity")

        if not last_activity:
            return False

        last_time = datetime.fromisoformat(last_activity)
        age = datetime.now() - last_time

        if age > timedelta(minutes=HEARTBEAT_STALE_MINUTES):
            return False  # Session is stale/abandoned

        return True  # Session is active

    except Exception:
        return False


def update_heartbeat():
    """Update the heartbeat file to indicate activity."""
    data = {
        "last_activity": datetime.now().isoformat(),
        "session_type": "autonomous",
        "user_present": False,
    }
    HEARTBEAT_FILE.write_text(json.dumps(data, indent=2))


def check_user_command() -> str | None:
    """Check iCloud folder for user command files."""
    if not ICLOUD_FOLDER.exists():
        return None

    for f in ICLOUD_FOLDER.iterdir():
        if f.name.startswith(".") or f.name == "status.txt":
            continue

        command = f.stem.lower()
        # Clean up the command file
        try:
            f.unlink()
        except Exception:
            pass

        return command

    return None


def get_pending_tasks() -> list:
    """
    Check for pending tasks.

    This reads from the task system. For now, we check a simple file.
    TODO: Integrate with the actual TaskQueue system.
    """
    tasks_file = GENESIS_DIR / ".pending_tasks.json"
    if tasks_file.exists():
        try:
            tasks = json.loads(tasks_file.read_text())
            return [t for t in tasks if t.get("status") == "pending"]
        except Exception:
            pass
    return []


def determine_task_complexity(prompt: str) -> str:
    """
    Determine task complexity for routing.

    Returns: 'simple', 'medium', or 'complex'
    """
    prompt_lower = prompt.lower()

    # Check for complex keywords
    for keyword in COMPLEX_KEYWORDS:
        if keyword in prompt_lower:
            return "complex"

    # Check for simple keywords
    for keyword in SIMPLE_KEYWORDS:
        if keyword in prompt_lower:
            return "simple"

    # Default to medium
    return "medium"


def invoke_aider(prompt: str, model: str = "ollama/qwen2.5-coder:32b") -> bool:
    """
    Invoke Aider with a local model (FREE).

    Args:
        prompt: The prompt/task
        model: The model to use

    Returns:
        True if invocation succeeded
    """
    log(f"Invoking Aider ({model}): {prompt[:50]}...")

    try:
        cmd = [
            AIDER_CLI,
            "--model", model,
            "--no-auto-commits",
            "--message", prompt,
        ]

        subprocess.Popen(
            cmd,
            cwd=GENESIS_DIR,
            stdout=open(LOG_FILE, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return True

    except Exception as e:
        log(f"Failed to invoke Aider: {e}")
        return False


def invoke_claude(prompt: str, wait: bool = False) -> bool:
    """
    Invoke Claude Code CLI with a prompt (uses subscription).

    Args:
        prompt: The prompt to send
        wait: If True, wait for completion. If False, run in background.

    Returns:
        True if invocation succeeded
    """
    log(f"Invoking Claude Code: {prompt[:50]}...")

    try:
        cmd = [CLAUDE_CLI, "-p", prompt]

        if wait:
            result = subprocess.run(
                cmd,
                cwd=GENESIS_DIR,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )
            # Check for rate limit or token exhaustion
            output = (result.stdout or "") + (result.stderr or "")
            if "rate limit" in output.lower() or "quota" in output.lower() or "token" in output.lower():
                mark_cloud_unavailable("claude", "Rate limit or quota exceeded")
                return False
            return result.returncode == 0
        else:
            # Run in background
            subprocess.Popen(
                cmd,
                cwd=GENESIS_DIR,
                stdout=open(LOG_FILE, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return True

    except subprocess.TimeoutExpired:
        log("Claude timed out")
        return False
    except Exception as e:
        log(f"Failed to invoke Claude: {e}")
        if "rate" in str(e).lower() or "limit" in str(e).lower():
            mark_cloud_unavailable("claude", str(e))
        return False


def invoke_gemini(prompt: str, wait: bool = False) -> bool:
    """
    Invoke Gemini CLI (Google, has FREE tier).

    Args:
        prompt: The prompt to send
        wait: If True, wait for completion.

    Returns:
        True if invocation succeeded
    """
    log(f"Invoking Gemini (FREE tier): {prompt[:50]}...")

    try:
        cmd = [GEMINI_CLI, "-p", prompt]

        if wait:
            result = subprocess.run(
                cmd,
                cwd=GENESIS_DIR,
                capture_output=True,
                text=True,
                timeout=600,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if "rate limit" in output.lower() or "quota" in output.lower():
                mark_cloud_unavailable("gemini", "Rate limit or quota exceeded")
                return False
            return result.returncode == 0
        else:
            subprocess.Popen(
                cmd,
                cwd=GENESIS_DIR,
                stdout=open(LOG_FILE, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return True

    except subprocess.TimeoutExpired:
        log("Gemini timed out")
        return False
    except Exception as e:
        log(f"Failed to invoke Gemini: {e}")
        if "rate" in str(e).lower() or "limit" in str(e).lower():
            mark_cloud_unavailable("gemini", str(e))
        return False


def invoke_codex(prompt: str, wait: bool = False) -> bool:
    """
    Invoke Codex CLI (OpenAI, uses subscription).

    Args:
        prompt: The prompt to send
        wait: If True, wait for completion.

    Returns:
        True if invocation succeeded
    """
    log(f"Invoking Codex (OpenAI): {prompt[:50]}...")

    try:
        cmd = [CODEX_CLI, "-p", prompt]

        if wait:
            result = subprocess.run(
                cmd,
                cwd=GENESIS_DIR,
                capture_output=True,
                text=True,
                timeout=600,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if "rate limit" in output.lower() or "quota" in output.lower():
                mark_cloud_unavailable("codex", "Rate limit or quota exceeded")
                return False
            return result.returncode == 0
        else:
            subprocess.Popen(
                cmd,
                cwd=GENESIS_DIR,
                stdout=open(LOG_FILE, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return True

    except subprocess.TimeoutExpired:
        log("Codex timed out")
        return False
    except Exception as e:
        log(f"Failed to invoke Codex: {e}")
        if "rate" in str(e).lower() or "limit" in str(e).lower():
            mark_cloud_unavailable("codex", str(e))
        return False


def invoke_task(prompt: str, force_tool: str = None) -> bool:
    """
    Smart task invocation - routes to appropriate tool based on complexity.

    Routing strategy (cost-optimized, with cloud fallback):
    - simple: Aider + codellama:13b (FREE)
    - medium: Aider + qwen2.5-coder:32b (FREE)
    - complex: Claude Code (subscription) -> falls back to Aider if unavailable
    - research: Claude Code (subscription) -> falls back to Gemini free tier

    IMPORTANT: If cloud services are unavailable (tokens exhausted, API down),
    automatically falls back to local models to keep work moving.

    Args:
        prompt: The task prompt
        force_tool: Optional - force 'aider', 'claude', 'gemini', or 'codex'

    Returns:
        True if invocation succeeded
    """
    # Check cloud service availability
    cloud_status = check_cloud_status()

    if force_tool == "aider":
        return invoke_aider(prompt)
    elif force_tool == "claude":
        if cloud_status.get("claude") is False:
            log("Claude unavailable - falling back to Aider with best local model")
            return invoke_aider(prompt, model="ollama/qwen2.5-coder:32b")
        return invoke_claude(prompt)
    elif force_tool == "gemini":
        if cloud_status.get("gemini") is False:
            log("Gemini unavailable - falling back to Aider")
            return invoke_aider(prompt, model="ollama/qwen2.5-coder:32b")
        return invoke_gemini(prompt)
    elif force_tool == "codex":
        if cloud_status.get("codex") is False:
            log("Codex unavailable - falling back to Aider")
            return invoke_aider(prompt, model="ollama/qwen2.5-coder:32b")
        return invoke_codex(prompt)

    # Auto-route based on complexity
    complexity = determine_task_complexity(prompt)

    if complexity == "simple":
        log("Task complexity: SIMPLE -> Using Aider (FREE)")
        return invoke_aider(prompt, model="ollama/codellama:13b")

    elif complexity == "medium":
        log("Task complexity: MEDIUM -> Using Aider (FREE)")
        return invoke_aider(prompt, model="ollama/qwen2.5-coder:32b")

    else:
        # Complex task - prefer Claude, but fall back if unavailable
        if cloud_status.get("claude") is False:
            log("Task complexity: COMPLEX but Claude unavailable")
            # Try Gemini free tier as first fallback
            if cloud_status.get("gemini") is not False:
                log("Falling back to Gemini (FREE tier)")
                return invoke_gemini(prompt)
            # Final fallback: local model with reasoning capability
            log("All cloud unavailable - using Aider with llama3.1:70b (local reasoning)")
            return invoke_aider(prompt, model="ollama/llama3.1:70b")

        log("Task complexity: COMPLEX -> Using Claude Code (subscription)")
        return invoke_claude(prompt)


def write_status(message: str):
    """Write status to iCloud for phone visibility."""
    if ICLOUD_FOLDER.exists():
        status_file = ICLOUD_FOLDER / "status.txt"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_file.write_text(f"[{timestamp}] {message}\n")


def main():
    """Main autonomous loop logic."""
    log("Autonomous loop check starting...")

    state = load_state()
    now = datetime.now()
    state["last_check"] = now.isoformat()

    # Check if there's an ACTIVE user session (not abandoned)
    if is_session_active():
        log("Active user session detected (heartbeat fresh). Skipping this cycle.")
        state["idle_since"] = None
        save_state(state)
        return

    # If Claude is running but session is stale, log it
    if is_claude_running():
        log("Claude running but session stale (no heartbeat). Proceeding with autonomous work.")

    # Check for user command via iCloud
    user_command = check_user_command()
    if user_command:
        log(f"User command received: {user_command}")
        state["idle_since"] = None
        state["last_activity"] = now.isoformat()

        if user_command == "continue":
            invoke_claude("Continue working on the current task. Check the task list and proceed.", wait=False)
        elif user_command == "status":
            write_status("Autonomous loop active. Checking for work...")
        elif user_command == "pause":
            write_status("Autonomous loop paused by user.")
            state["paused"] = True
        elif user_command == "resume":
            state["paused"] = False
            write_status("Autonomous loop resumed.")
        else:
            # Treat as a custom prompt - route based on complexity
            invoke_task(user_command)

        save_state(state)
        return

    # Check if paused
    if state.get("paused"):
        log("Autonomous loop is paused. Drop 'resume' file to continue.")
        return

    # Check for pending tasks
    pending_tasks = get_pending_tasks()
    if pending_tasks:
        log(f"Found {len(pending_tasks)} pending tasks. Routing to appropriate tool...")
        state["idle_since"] = None
        state["last_activity"] = now.isoformat()

        task = pending_tasks[0]
        prompt = f"Continue working on task: {task.get('subject', 'Unknown')}. {task.get('description', '')}"
        invoke_task(prompt)  # Smart routing based on task complexity

        update_heartbeat()
        save_state(state)
        return

    # No pending tasks - check idle time
    if state["idle_since"] is None:
        state["idle_since"] = now.isoformat()
        log("No pending tasks. Starting idle timer.")
        save_state(state)
        return

    idle_since = datetime.fromisoformat(state["idle_since"])
    idle_duration = now - idle_since

    if idle_duration < timedelta(minutes=10):
        log(f"Idle for {idle_duration.seconds // 60} minutes. Waiting for 10 min threshold.")
        save_state(state)
        return

    # Idle for 10+ minutes - make autonomous decision
    log("Idle for 10+ minutes. Making autonomous decision...")

    priorities = load_priorities()
    priority_index = state.get("current_priority_index", 0)

    if priority_index >= len(priorities):
        log("All priorities completed! Waiting for user direction.")
        write_status("All roadmap priorities completed. Awaiting new direction.")
        save_state(state)
        return

    current_priority = priorities[priority_index]
    log(f"Autonomous decision: {current_priority['name']}")
    write_status(f"Auto-starting: {current_priority['name']}")

    # Invoke Claude with the priority prompt
    invoke_claude(current_priority["prompt"], wait=False)

    state["idle_since"] = None
    state["last_activity"] = now.isoformat()
    update_heartbeat()
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"Error in autonomous loop: {e}")
        sys.exit(1)
