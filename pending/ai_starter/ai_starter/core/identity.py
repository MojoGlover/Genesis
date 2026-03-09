"""Mission parsing and identity management."""

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class Identity(BaseModel):
    """Structured agent identity from mission file."""
    name: str
    role: str
    owner: str
    principles: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    raw_content: str

    @field_validator("name", "role", "owner")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("Field cannot be empty")
        return v.strip()


def load_identity(mission_path: Path | str) -> Identity:
    """Parse mission.txt and return structured Identity."""
    path = Path(mission_path)
    if not path.exists():
        raise FileNotFoundError(f"Mission file not found: {path}")

    content = path.read_text()
    lines = content.strip().split("\n")

    name = ""
    role = ""
    owner = ""
    principles = []
    constraints = []
    current_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("IDENTITY:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("ROLE:"):
            role = line.split(":", 1)[1].strip()
        elif line.startswith("OWNER:"):
            owner = line.split(":", 1)[1].strip()
        elif line.startswith("PRINCIPLES:"):
            current_section = "principles"
        elif line.startswith("CONSTRAINTS:"):
            current_section = "constraints"
        elif line.startswith("-") and current_section:
            item = line.lstrip("-").strip()
            if current_section == "principles":
                principles.append(item)
            elif current_section == "constraints":
                constraints.append(item)

    return Identity(
        name=name,
        role=role,
        owner=owner,
        principles=principles,
        constraints=constraints,
        raw_content=content,
    )


def assert_identity_loaded(identity: Identity | None) -> None:
    """Ensure identity is valid before agent boot."""
    if identity is None:
        raise RuntimeError("Identity not loaded. Agent cannot start without mission.txt")
    if not identity.name or not identity.role or not identity.owner:
        raise RuntimeError("Identity incomplete. IDENTITY, ROLE, and OWNER are required.")


def get_system_prompt(identity: Identity) -> str:
    """Format identity into LLM system prompt."""
    prompt = f"""You are {identity.name}.

ROLE: {identity.role}

You operate under the authority of: {identity.owner}

PRINCIPLES:
"""
    for p in identity.principles:
        prompt += f"- {p}\n"

    prompt += "\nCONSTRAINTS (you MUST follow these):\n"
    for c in identity.constraints:
        prompt += f"- {c}\n"

    return prompt.strip()
