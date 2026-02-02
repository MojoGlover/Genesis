"""
Engineer0 Team Management

Manages the engineer team (Engineers 1-9, EngineerX).
Each engineer has a dedicated role and provider.

Team Structure:
- Engineer 0 (Zero): Supervisor - manages all, local reasoning
- Engineer 1: Claude specialist - complex architecture
- Engineer 2: OpenAI/Codex specialist - code generation
- Engineer 3: Gemini specialist - documentation, research
- Engineer 4: Ollama/Local specialist - fast iteration
- Engineer 5-9: General purpose, spawned as needed
- Engineer X (10): Tester - testing and QA
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EngineerStatus(Enum):
    """Status of an engineer."""
    OFFLINE = "offline"
    IDLE = "idle"
    BUSY = "busy"
    DEGRADED = "degraded"


@dataclass
class EngineerProfile:
    """Profile for an engineer in the team."""
    number: int
    name: str
    role: str
    provider: str
    specialization: List[str]
    status: EngineerStatus = EngineerStatus.OFFLINE

    # Tracking
    tasks_completed: int = 0
    tasks_failed: int = 0
    current_task: Optional[str] = None
    last_active: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "number": self.number,
            "name": self.name,
            "role": self.role,
            "provider": self.provider,
            "specialization": self.specialization,
            "status": self.status.value,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "current_task": self.current_task,
            "last_active": self.last_active,
        }


# The Engineer Team
ENGINEER_TEAM = {
    0: EngineerProfile(
        number=0,
        name="Zero",
        role="Supervisor",
        provider="ollama",  # Uses local for reasoning
        specialization=["supervision", "routing", "coordination", "planning"]
    ),
    1: EngineerProfile(
        number=1,
        name="One",
        role="Architect",
        provider="claude",
        specialization=["architecture", "complex_reasoning", "multi_file", "research"]
    ),
    2: EngineerProfile(
        number=2,
        name="Two",
        role="Developer",
        provider="codex",
        specialization=["code_generation", "debugging", "refactoring"]
    ),
    3: EngineerProfile(
        number=3,
        name="Three",
        role="Researcher",
        provider="gemini",
        specialization=["documentation", "research", "explanation", "analysis"]
    ),
    4: EngineerProfile(
        number=4,
        name="Four",
        role="Rapid Developer",
        provider="aider",  # Uses local Ollama
        specialization=["fast_iteration", "simple_fixes", "formatting", "linting"]
    ),
    5: EngineerProfile(
        number=5,
        name="Five",
        role="General",
        provider="auto",  # Routes based on task
        specialization=["general_purpose"]
    ),
    6: EngineerProfile(
        number=6,
        name="Six",
        role="General",
        provider="auto",
        specialization=["general_purpose"]
    ),
    7: EngineerProfile(
        number=7,
        name="Seven",
        role="General",
        provider="auto",
        specialization=["general_purpose"]
    ),
    8: EngineerProfile(
        number=8,
        name="Eight",
        role="General",
        provider="auto",
        specialization=["general_purpose"]
    ),
    9: EngineerProfile(
        number=9,
        name="Nine",
        role="General",
        provider="auto",
        specialization=["general_purpose"]
    ),
    10: EngineerProfile(
        number=10,
        name="X",
        role="Tester",
        provider="local",  # Uses EngineerX agent directly
        specialization=["testing", "qa", "linting", "type_checking"]
    ),
}


class TeamManager:
    """
    Manages the engineer team.

    Engineer0 uses this to:
    - Assign tasks to the right engineer based on specialization
    - Track engineer status and workload
    - Monitor team performance
    - Handle engineer failover
    """

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.team = {k: EngineerProfile(**v.__dict__) for k, v in ENGINEER_TEAM.items()}
        self._load_state()

    def _load_state(self) -> None:
        """Load team state from disk."""
        if not self.state_path.exists():
            return

        try:
            data = json.loads(self.state_path.read_text())
            for num_str, state in data.items():
                num = int(num_str)
                if num in self.team:
                    self.team[num].status = EngineerStatus(state.get("status", "offline"))
                    self.team[num].tasks_completed = state.get("tasks_completed", 0)
                    self.team[num].tasks_failed = state.get("tasks_failed", 0)
                    self.team[num].current_task = state.get("current_task")
                    self.team[num].last_active = state.get("last_active")
        except Exception as e:
            logger.error(f"Failed to load team state: {e}")

    def _save_state(self) -> None:
        """Save team state to disk."""
        data = {
            str(num): {
                "status": eng.status.value,
                "tasks_completed": eng.tasks_completed,
                "tasks_failed": eng.tasks_failed,
                "current_task": eng.current_task,
                "last_active": eng.last_active,
            }
            for num, eng in self.team.items()
        }
        try:
            self.state_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save team state: {e}")

    def get_engineer(self, number: int) -> Optional[EngineerProfile]:
        """Get an engineer by number."""
        return self.team.get(number)

    def get_available_engineers(self) -> List[EngineerProfile]:
        """Get all available (idle) engineers."""
        return [
            eng for eng in self.team.values()
            if eng.status == EngineerStatus.IDLE and eng.number != 0  # Exclude Zero
        ]

    def select_engineer(self, task_type: str, complexity: str) -> Optional[EngineerProfile]:
        """
        Select the best engineer for a task.

        Routing logic:
        - Complex architecture/research → Engineer 1 (Claude)
        - Code generation/debugging → Engineer 2 (Codex)
        - Documentation/research → Engineer 3 (Gemini)
        - Simple/fast tasks → Engineer 4 (Aider/Ollama)
        - Testing → Engineer X (10)
        - General → Engineers 5-9 (round-robin)
        """
        # Testing goes to Engineer X
        if task_type in ["test", "testing", "qa", "lint"]:
            return self.team[10]

        # Complex tasks go to Engineer 1 (Claude)
        if complexity == "complex" or task_type in ["architecture", "research", "planning"]:
            eng = self.team[1]
            if eng.status in [EngineerStatus.IDLE, EngineerStatus.OFFLINE]:
                return eng

        # Code generation to Engineer 2 (Codex)
        if task_type in ["code", "generate", "debug", "fix"]:
            eng = self.team[2]
            if eng.status in [EngineerStatus.IDLE, EngineerStatus.OFFLINE]:
                return eng

        # Documentation/research to Engineer 3 (Gemini)
        if task_type in ["document", "research", "explain", "analyze"]:
            eng = self.team[3]
            if eng.status in [EngineerStatus.IDLE, EngineerStatus.OFFLINE]:
                return eng

        # Simple/fast to Engineer 4 (Aider)
        if complexity == "simple" or task_type in ["format", "lint", "typo"]:
            eng = self.team[4]
            if eng.status in [EngineerStatus.IDLE, EngineerStatus.OFFLINE]:
                return eng

        # Fallback: find any available general engineer (5-9)
        for num in range(5, 10):
            eng = self.team[num]
            if eng.status in [EngineerStatus.IDLE, EngineerStatus.OFFLINE]:
                return eng

        # Last resort: use Engineer 4 (always available via local)
        return self.team[4]

    def assign_task(self, engineer_num: int, task_description: str) -> bool:
        """Assign a task to an engineer."""
        if engineer_num not in self.team:
            return False

        eng = self.team[engineer_num]
        eng.status = EngineerStatus.BUSY
        eng.current_task = task_description[:100]
        eng.last_active = datetime.now().isoformat()

        self._save_state()
        logger.info(f"Assigned task to Engineer {eng.number} ({eng.name})")
        return True

    def complete_task(self, engineer_num: int, success: bool) -> None:
        """Mark an engineer's task as complete."""
        if engineer_num not in self.team:
            return

        eng = self.team[engineer_num]
        eng.status = EngineerStatus.IDLE
        eng.current_task = None
        eng.last_active = datetime.now().isoformat()

        if success:
            eng.tasks_completed += 1
        else:
            eng.tasks_failed += 1

        self._save_state()

    def set_status(self, engineer_num: int, status: EngineerStatus) -> None:
        """Set an engineer's status."""
        if engineer_num in self.team:
            self.team[engineer_num].status = status
            self._save_state()

    def get_team_status(self) -> Dict[str, Any]:
        """Get status of the entire team."""
        return {
            "total": len(self.team),
            "idle": len([e for e in self.team.values() if e.status == EngineerStatus.IDLE]),
            "busy": len([e for e in self.team.values() if e.status == EngineerStatus.BUSY]),
            "offline": len([e for e in self.team.values() if e.status == EngineerStatus.OFFLINE]),
            "engineers": {num: eng.to_dict() for num, eng in self.team.items()}
        }

    def get_provider_for_engineer(self, engineer_num: int) -> str:
        """Get the provider for an engineer."""
        eng = self.team.get(engineer_num)
        if not eng:
            return "aider"  # Default

        if eng.provider == "auto":
            return "aider"  # General engineers use local by default

        return eng.provider
