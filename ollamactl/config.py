"""ollamactl/config.py — Ollama connection config."""

OLLAMA_BASE    = "http://100.113.209.66:11434"
DEFAULT_MODEL  = "llama3.2:3b"
TIMEOUT        = 10  # seconds for status check

# Models that Computer Black uses or might use
KNOWN_MODELS = [
    "llama3.2:3b",      # MadJanet default — fast, small
    "llama3.2:1b",      # Ultra-light, slowest devices
    "llama3.1:8b",      # Smarter, needs more VRAM
    "mistral:7b",       # Good alternative
    "dolphin-mistral",  # Already pulled on Mac
    "blackzero",        # Already pulled on Mac
]
