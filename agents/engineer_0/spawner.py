"""
Engineer0 Agent Spawner

Spawns temporary agents to accomplish tasks in Engineer0's purview.
Each agent is a subprocess that runs a specific task and reports back.
"""

from __future__ import annotations
import asyncio
import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import time

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    """Roles that spawned agents can fulfill."""
    CODER = "coder"           # Write/modify code
    TESTER = "tester"         # Run tests (delegates to EngineerX)
    RESEARCHER = "researcher" # Research/explore codebase
    REVIEWER = "reviewer"     # Code review
    FIXER = "fixer"          # Fix bugs/issues
    DOCUMENTER = "documenter" # Write documentation
    ARCHITECT = "architect"   # Design/plan
    GENERAL = "general"       # General purpose


class AgentStatus(Enum):
    """Status of a spawned agent."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class SpawnedAgent:
    """A spawned agent instance."""
    agent_id: str
    role: AgentRole
    task: str
    status: AgentStatus = AgentStatus.PENDING

    # Tracking
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Execution
    provider: Optional[str] = None
    pid: Optional[int] = None
    result: Optional[str] = None
    error: Optional[str] = None

    # Metadata
    parent_task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "task": self.task,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "provider": self.provider,
            "result": self.result[:500] if self.result else None,
            "error": self.error,
        }


class AgentSpawner:
    """
    Spawns temporary agents to accomplish tasks.

    Engineer0 uses this to delegate work:
    - Coding tasks → spawn coder agent (uses Aider/Claude)
    - Testing tasks → delegate to EngineerX
    - Research tasks → spawn researcher agent
    - Review tasks → spawn reviewer agent

    Agents run as subprocesses and report back when done.
    """

    def __init__(
        self,
        working_dir: Path,
        log_dir: Path,
        router,  # TaskRouter instance
        max_concurrent: int = 5
    ):
        self.working_dir = working_dir
        self.log_dir = log_dir
        self.router = router
        self.max_concurrent = max_concurrent

        # Active agents
        self._agents: Dict[str, SpawnedAgent] = {}
        self._processes: Dict[str, subprocess.Popen] = {}

        # Statistics
        self.stats = {
            "spawned": 0,
            "completed": 0,
            "failed": 0,
            "by_role": {}
        }

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def spawn(
        self,
        role: AgentRole,
        task: str,
        provider: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        wait: bool = False,
        timeout: float = 600.0
    ) -> SpawnedAgent:
        """
        Spawn an agent to accomplish a task.

        Args:
            role: The role this agent will fulfill
            task: Task description/prompt
            provider: Force specific provider (otherwise auto-route)
            parent_task_id: Parent task this agent is working on
            metadata: Additional metadata
            wait: Wait for completion
            timeout: Timeout in seconds

        Returns:
            SpawnedAgent instance
        """
        agent_id = f"agent_{role.value}_{uuid.uuid4().hex[:8]}"

        agent = SpawnedAgent(
            agent_id=agent_id,
            role=role,
            task=task,
            parent_task_id=parent_task_id,
            metadata=metadata or {}
        )

        # Determine provider based on role if not specified
        if not provider:
            provider = self._select_provider(role, task)

        agent.provider = provider

        self._agents[agent_id] = agent
        self.stats["spawned"] += 1
        self.stats["by_role"][role.value] = self.stats["by_role"].get(role.value, 0) + 1

        logger.info(f"Spawning {role.value} agent: {agent_id}")

        if wait:
            self._run_sync(agent, timeout)
        else:
            self._run_async(agent)

        return agent

    def _select_provider(self, role: AgentRole, task: str) -> str:
        """Select provider based on role."""
        # Testers should use EngineerX directly
        if role == AgentRole.TESTER:
            return "engineer_x"

        # Complex roles prefer Claude
        if role in [AgentRole.ARCHITECT, AgentRole.RESEARCHER]:
            return self.router.route(task, complexity="complex")

        # Code-heavy roles use Aider by default (free)
        if role in [AgentRole.CODER, AgentRole.FIXER]:
            return self.router.route(task, complexity="medium")

        # Default
        return self.router.route(task, complexity="medium")

    def _run_sync(self, agent: SpawnedAgent, timeout: float) -> None:
        """Run agent synchronously (blocking)."""
        agent.status = AgentStatus.RUNNING
        agent.started_at = time.time()

        try:
            if agent.provider == "engineer_x":
                result = self._invoke_engineer_x(agent.task, timeout)
            else:
                result = self.router.invoke(
                    prompt=self._build_prompt(agent),
                    provider=agent.provider,
                    complexity="medium",
                    wait=True,
                    timeout=timeout
                )

            if result.success:
                agent.status = AgentStatus.COMPLETED
                agent.result = result.output
                self.stats["completed"] += 1
            else:
                agent.status = AgentStatus.FAILED
                agent.error = result.error
                self.stats["failed"] += 1

        except subprocess.TimeoutExpired:
            agent.status = AgentStatus.TIMEOUT
            agent.error = f"Timeout after {timeout}s"
            self.stats["failed"] += 1
        except Exception as e:
            agent.status = AgentStatus.FAILED
            agent.error = str(e)
            self.stats["failed"] += 1
        finally:
            agent.completed_at = time.time()

    def _run_async(self, agent: SpawnedAgent) -> None:
        """Run agent asynchronously (non-blocking)."""
        agent.status = AgentStatus.RUNNING
        agent.started_at = time.time()

        log_file = self.log_dir / f"{agent.agent_id}.log"

        if agent.provider == "engineer_x":
            # EngineerX is a local agent
            cmd = [
                "python3", "-m", "agents.engineer_x",
                "--task", agent.task
            ]
        else:
            # Use router's provider
            provider_path = {
                "aider": "/Users/darnieglover/Library/Python/3.11/bin/aider",
                "claude": "/opt/homebrew/bin/claude",
                "gemini": "/opt/homebrew/bin/gemini",
                "codex": "/opt/homebrew/bin/codex"
            }.get(agent.provider, "claude")

            cmd = [provider_path, "-p", self._build_prompt(agent)]

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=self.working_dir,
                stdout=open(log_file, "w"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            agent.pid = proc.pid
            self._processes[agent.agent_id] = proc

            logger.info(f"Agent {agent.agent_id} started (PID: {proc.pid})")

        except Exception as e:
            agent.status = AgentStatus.FAILED
            agent.error = str(e)
            self.stats["failed"] += 1

    def _build_prompt(self, agent: SpawnedAgent) -> str:
        """Build the prompt for the agent based on role."""
        role_context = {
            AgentRole.CODER: "You are a coding agent. Write clean, working code.",
            AgentRole.TESTER: "You are a testing agent. Write and run tests.",
            AgentRole.RESEARCHER: "You are a research agent. Explore and analyze.",
            AgentRole.REVIEWER: "You are a code review agent. Review for quality and issues.",
            AgentRole.FIXER: "You are a bug-fixing agent. Identify and fix the issue.",
            AgentRole.DOCUMENTER: "You are a documentation agent. Write clear docs.",
            AgentRole.ARCHITECT: "You are an architecture agent. Design and plan.",
            AgentRole.GENERAL: "You are a general-purpose agent.",
        }

        context = role_context.get(agent.role, "")
        return f"{context}\n\nTask: {agent.task}"

    def _invoke_engineer_x(self, task: str, timeout: float):
        """Invoke EngineerX for testing tasks."""
        from agents.engineer_x import create_engineer_x

        engineer_x = create_engineer_x()

        # Determine test type from task
        if "pytest" in task.lower() or "test" in task.lower():
            result = engineer_x.execute_task({"type": "run_pytest"})
        elif "lint" in task.lower() or "flake8" in task.lower():
            result = engineer_x.execute_task({"type": "run_lint"})
        elif "type" in task.lower() or "mypy" in task.lower():
            result = engineer_x.execute_task({"type": "run_typecheck"})
        else:
            result = engineer_x.execute_task({"type": "run_all"})

        # Convert to InvocationResult-like object
        class Result:
            success = result.get("success", False)
            output = json.dumps(result)
            error = None if result.get("success") else "Tests failed"

        return Result()

    def check_agent(self, agent_id: str) -> Optional[SpawnedAgent]:
        """Check on an agent's status."""
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        # If running async, check process
        if agent.status == AgentStatus.RUNNING and agent_id in self._processes:
            proc = self._processes[agent_id]
            if proc.poll() is not None:
                # Process finished
                agent.completed_at = time.time()

                log_file = self.log_dir / f"{agent_id}.log"
                if log_file.exists():
                    agent.result = log_file.read_text()[-5000:]  # Last 5KB

                if proc.returncode == 0:
                    agent.status = AgentStatus.COMPLETED
                    self.stats["completed"] += 1
                else:
                    agent.status = AgentStatus.FAILED
                    agent.error = f"Exit code: {proc.returncode}"
                    self.stats["failed"] += 1

                del self._processes[agent_id]

        return agent

    def cancel_agent(self, agent_id: str) -> bool:
        """Cancel a running agent."""
        agent = self._agents.get(agent_id)
        if not agent or agent.status != AgentStatus.RUNNING:
            return False

        if agent_id in self._processes:
            try:
                self._processes[agent_id].terminate()
                del self._processes[agent_id]
            except Exception:
                pass

        agent.status = AgentStatus.CANCELLED
        agent.completed_at = time.time()

        logger.info(f"Cancelled agent: {agent_id}")
        return True

    def get_active_agents(self) -> List[SpawnedAgent]:
        """Get all active (running) agents."""
        return [
            a for a in self._agents.values()
            if a.status == AgentStatus.RUNNING
        ]

    def get_agent_count(self) -> int:
        """Get count of running agents."""
        return len([a for a in self._agents.values() if a.status == AgentStatus.RUNNING])

    def can_spawn(self) -> bool:
        """Check if we can spawn more agents."""
        return self.get_agent_count() < self.max_concurrent

    def cleanup_completed(self, older_than_minutes: float = 60) -> int:
        """Remove completed agents older than threshold."""
        cutoff = time.time() - (older_than_minutes * 60)
        removed = 0

        for agent_id in list(self._agents.keys()):
            agent = self._agents[agent_id]
            if agent.status in [AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED]:
                if agent.completed_at and agent.completed_at < cutoff:
                    del self._agents[agent_id]
                    removed += 1

        return removed

    def get_statistics(self) -> Dict[str, Any]:
        """Get spawner statistics."""
        return {
            **self.stats,
            "active": self.get_agent_count(),
            "max_concurrent": self.max_concurrent
        }

    def spawn_coder(self, task: str, **kwargs) -> SpawnedAgent:
        """Convenience: spawn a coder agent."""
        return self.spawn(AgentRole.CODER, task, **kwargs)

    def spawn_tester(self, task: str, **kwargs) -> SpawnedAgent:
        """Convenience: spawn a tester agent (uses EngineerX)."""
        return self.spawn(AgentRole.TESTER, task, **kwargs)

    def spawn_researcher(self, task: str, **kwargs) -> SpawnedAgent:
        """Convenience: spawn a researcher agent."""
        return self.spawn(AgentRole.RESEARCHER, task, **kwargs)

    def spawn_reviewer(self, task: str, **kwargs) -> SpawnedAgent:
        """Convenience: spawn a code reviewer agent."""
        return self.spawn(AgentRole.REVIEWER, task, **kwargs)

    def spawn_fixer(self, task: str, **kwargs) -> SpawnedAgent:
        """Convenience: spawn a bug fixer agent."""
        return self.spawn(AgentRole.FIXER, task, **kwargs)
