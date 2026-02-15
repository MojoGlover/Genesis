"""Configuration management with Pydantic + YAML."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class OllamaSettings(BaseModel):
    """Ollama connection settings."""
    base_url: str = "http://localhost:11434"
    model: str = "phi3:mini"
    temperature: float = 0.7
    max_tokens: int = 2048


class LoopSettings(BaseModel):
    """Agent loop timing and retry settings."""
    interval_seconds: int = 30
    max_retries: int = 3
    task_timeout_seconds: int = 300


class Settings(BaseSettings):
    """Main application settings."""
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    loop: LoopSettings = Field(default_factory=LoopSettings)
    data_dir: str = "~/.ai_starter"
    log_level: str = "INFO"

    class Config:
        env_prefix = "AI_STARTER_"
        env_nested_delimiter = "__"


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Load settings from YAML file with environment variable overrides."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return Settings()

    with open(config_path) as f:
        config_data = yaml.safe_load(f) or {}

    # Merge with env vars (Pydantic handles this automatically)
    return Settings(**config_data)
