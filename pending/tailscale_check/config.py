"""tailscale_check/config.py — host registry for Tailscale preflight."""

# All Computer Black Tailscale hosts
HOSTS = {
    "ollama": {
        "ip":   "100.113.209.66",
        "port": 11434,
        "label": "Ollama (Mac local brain)",
        "required": True,   # fail preflight if unreachable
    },
    "mac": {
        "ip":   "100.113.209.66",
        "port": 22,
        "label": "Mac SSH",
        "required": False,
    },
    "engineer0": {
        "ip":   "100.113.209.66",
        "port": 5001,
        "label": "Engineer0 API",
        "required": False,
    },
    "genesis": {
        "ip":   "100.113.209.66",
        "port": 7860,
        "label": "GENESIS Gradio",
        "required": False,
    },
}

TIMEOUT_SECONDS = 5
