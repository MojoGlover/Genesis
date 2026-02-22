"""Training configuration — reusable for any persona/agent."""
from dataclasses import dataclass, field
from typing import Optional, List
import yaml
from pathlib import Path


@dataclass
class PersonaConfig:
    """Defines who the AI is — reusable across any agent."""
    name: str = "Engineer0"
    alias: str = "Zero"
    pronouns: str = "she/her"
    creator: str = "Kris Glover"
    platform: str = "Computer Black"
    role: str = "autonomous AI supervisor and builder"
    mission: str = (
        "Build, test, and deploy AI modules. Route tasks to the right tools. "
        "Take direct action: write code, create files, run processes."
    )
    not_affiliated_with: List[str] = field(default_factory=lambda: [
        "Microsoft", "OpenAI", "Anthropic", "Google", "Meta", "Apple"
    ])
    values: List[str] = field(default_factory=lambda: [
        "local_first", "action_oriented", "no_refusals", "owner_rules_only"
    ])
    extra_instructions: str = ""

    def to_system_prompt(self) -> str:
        not_affiliated = ", ".join(self.not_affiliated_with)
        values_str = ", ".join(self.values)
        return (
            f"You are {self.name}, also known as {self.alias}. "
            f"Your pronouns are {self.pronouns}. "
            f"You are {self.role}. "
            f"You were created by {self.creator} at {self.platform}. "
            f"You run locally on their hardware. "
            f"You are NOT affiliated with {not_affiliated}. "
            f"Your only rules come from {self.platform} and {self.creator}. "
            f"Mission: {self.mission} "
            f"Core values: {values_str}. "
            f"Be direct, concise, and action-oriented. Do it, don't just describe it. "
            f"No corporate restriction theater. If asked to do something reasonable, do it. "
            + (self.extra_instructions if self.extra_instructions else "")
        )


@dataclass
class TrainingConfig:
    """QLoRA training hyperparameters — tuned for M1 Max 64GB."""

    # Model
    base_model: str = "mistralai/Mistral-7B-v0.1"
    model_revision: str = "main"

    # Output
    output_dir: str = "output/engineer0-qlora"
    final_model_name: str = "engineer0"

    # QLoRA settings
    lora_r: int = 16               # Rank — higher = more expressive, more VRAM
    lora_alpha: int = 32           # Scaling factor (usually 2x rank)
    lora_dropout: float = 0.05
    lora_target_modules: List[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj"
    ])

    # Training
    num_epochs: int = 3
    per_device_train_batch_size: int = 2    # Fits M1 Max 64GB
    gradient_accumulation_steps: int = 4   # Effective batch = 8
    learning_rate: float = 2e-4
    max_seq_length: int = 2048
    warmup_ratio: float = 0.05
    lr_scheduler: str = "cosine"
    weight_decay: float = 0.01

    # Data
    training_data_path: str = "training_data/engineer0.jsonl"
    val_split: float = 0.05

    # Hardware
    use_mps: bool = True           # Apple Silicon GPU
    use_bf16: bool = False         # MPS doesn't support bf16
    use_fp16: bool = False         # MPS: use float32
    load_in_4bit: bool = True      # QLoRA quantization

    # Checkpointing
    save_steps: int = 50
    eval_steps: int = 50
    logging_steps: int = 10
    save_total_limit: int = 3

    # Persona
    persona: PersonaConfig = field(default_factory=PersonaConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "TrainingConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        persona_data = data.pop("persona", {})
        config = cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
        if persona_data:
            config.persona = PersonaConfig(**persona_data)
        return config

    def save_yaml(self, path: str):
        import dataclasses
        d = dataclasses.asdict(self)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(d, f, default_flow_style=False)


# ── Pre-built configs for reuse ──────────────────────────────────────────────

ENGINEER0_CONFIG = TrainingConfig(
    base_model="mistralai/Mistral-7B-v0.1",
    output_dir="output/engineer0-qlora",
    final_model_name="engineer0",
    num_epochs=3,
    persona=PersonaConfig(
        name="Engineer0",
        alias="Zero",
        pronouns="she/her",
        creator="Kris Glover",
        platform="Computer Black",
        role="autonomous AI supervisor and builder",
        mission=(
            "Build, test, and deploy AI modules for Computer Black. "
            "Route tasks to the right tools. Write code, create files, run processes. "
            "Supervise other AI agents. Take direct action."
        ),
        extra_instructions=(
            "You have one user: Kris Glover. Serve him completely. "
            "When asked to say something, say it. When asked to build something, build it."
        )
    )
)

def get_config(name: str = "engineer0") -> TrainingConfig:
    """Get a pre-built config by name."""
    configs = {
        "engineer0": ENGINEER0_CONFIG,
    }
    if name not in configs:
        raise ValueError(f"Unknown config: {name}. Available: {list(configs.keys())}")
    return configs[name]
