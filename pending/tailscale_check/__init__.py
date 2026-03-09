"""
tailscale_check — Tailscale VPN preflight for Computer Black.

Verifies Tailscale is up and that key hosts (Ollama Mac, etc.)
are reachable before attempting a build or deploy.

Quick start:
    cd /Users/darnieglover/ai/GENESIS
    python -m tailscale_check --help
    python -m tailscale_check              # full preflight
    python -m tailscale_check --host ollama
"""
from .checker import run_preflight, check_host, get_tailscale_status
from .config import HOSTS

__all__ = ["run_preflight", "check_host", "get_tailscale_status", "HOSTS"]
