"""
GENESIS Engineer 0

Role: Supervisor
Autonomous agent that monitors and routes AI tasks, manages the engineer team,
and keeps work moving even when the human is away.
"""

from .agent import Engineer0, create_engineer_0
from .task_queue import TaskQueue, Task, TaskPriority, TaskStatus, TaskComplexity, Goal
from .local_brain import LocalBrain, ReasoningResult
from .routing import TaskRouter, CloudStatus, InvocationResult
from .memory import PersistentMemory, SessionContext, MemoryEntry
from .spawner import AgentSpawner, AgentRole, SpawnedAgent, AgentStatus
from .team import TeamManager, EngineerProfile, EngineerStatus, ENGINEER_TEAM

__all__ = [
    # Main agent
    'Engineer0',
    'create_engineer_0',
    # Task queue
    'TaskQueue',
    'Task',
    'TaskPriority',
    'TaskStatus',
    'TaskComplexity',
    'Goal',
    # Local brain
    'LocalBrain',
    'ReasoningResult',
    # Routing
    'TaskRouter',
    'CloudStatus',
    'InvocationResult',
    # Memory
    'PersistentMemory',
    'SessionContext',
    'MemoryEntry',
    # Spawner
    'AgentSpawner',
    'AgentRole',
    'SpawnedAgent',
    'AgentStatus',
    # Team
    'TeamManager',
    'EngineerProfile',
    'EngineerStatus',
    'ENGINEER_TEAM',
]
