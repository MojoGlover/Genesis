"""
ollamactl — Ollama local brain manager for Computer Black.

Pull models, list what's loaded, switch active model, check status,
and restart the Ollama service — all without SSH'ing to the Mac manually.

Quick start:
    cd /Users/darnieglover/ai/GENESIS
    python -m ollamactl --help
    python -m ollamactl --status
    python -m ollamactl --list
    python -m ollamactl --pull llama3.2:3b
    python -m ollamactl --set-model llama3.2:3b
"""
from .client import OllamaClient, check_status, list_models, pull_model
from .config import OLLAMA_BASE, DEFAULT_MODEL

__all__ = [
    "OllamaClient", "check_status", "list_models",
    "pull_model", "OLLAMA_BASE", "DEFAULT_MODEL",
]
