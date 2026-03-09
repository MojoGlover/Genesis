"""
Mission Statement Loader
Loads AI-specific mission and goals
"""
from pathlib import Path
from typing import Optional


def load_mission() -> str:
    """
    Load mission statement from MISSION.md
    Returns default if not found
    """
    mission_file = Path("MISSION.md")
    
    if mission_file.exists():
        return mission_file.read_text()
    
    # Default fallback
    return """
# Default GENESIS Mission
General-purpose AI assistant. 
No specific mission configured - copy MISSION.md.example to MISSION.md and customize.
"""


def get_system_prompt(base_prompt: str = "") -> str:
    """
    Combine base prompt with mission
    """
    mission = load_mission()
    
    return f"""
{base_prompt}

{mission}

Remember: Your mission guides HOW you help, not WHETHER you help.
"""
