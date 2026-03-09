# Installation Guide

## Prerequisites

- Python 3.10+
- Ollama installed and running

## Setup

1. **Install ai_starter**:
```bash
cd ~/ai/GENESIS/ai_starter
pip install -e .
```

2. **Install dev dependencies (optional)**:
```bash
pip install -e ".[dev]"
```

3. **Configure your mission**:
```bash
# Copy the example
cp mission.example.txt mission.txt

# Edit with your agent's identity
nano mission.txt
```

4. **Ensure Ollama is running**:
```bash
# Start Ollama
ollama serve

# Pull a model (in another terminal)
ollama pull phi3:mini
```

5. **Run tests** (optional):
```bash
cd ~/ai/GENESIS/ai_starter
PYTHONPATH=. python3 tests/test_core.py
PYTHONPATH=. python3 tests/test_llm.py
PYTHONPATH=. python3 tests/test_memory.py
```

Or with pytest:
```bash
pytest tests/ -v
```

6. **Run the agent**:
```bash
# One-shot mode (process one task and exit)
python3 -m ai_starter.main --once

# Continuous mode
python3 -m ai_starter.main

# Or if installed:
ai-starter --once
```

## Configuration

Edit `config.yaml` to customize:
- Ollama model and connection
- Loop timing
- Data directory
- Log level

## Directory Structure

```
ai_starter/
├── README.md           # Main documentation
├── INSTALL.md          # This file
├── pyproject.toml      # Package definition
├── config.yaml         # Configuration
├── mission.txt         # YOUR agent identity (required)
├── mission.example.txt # Example mission file
├── ai_starter/         # Main package
│   ├── config/         # Settings management
│   ├── core/           # State, identity, loop
│   ├── llm/            # Ollama client, prompts, parsing
│   ├── memory/         # SQLite storage, retrieval
│   ├── tools/          # Tool registry, executor
│   ├── improvement/    # Self-eval, adaptation
│   └── main.py         # Entry point
└── tests/              # Unit tests
```

## Troubleshooting

**Module not found errors**:
```bash
# Use PYTHONPATH when running from source
PYTHONPATH=/Users/darnieglover/ai/GENESIS/ai_starter python3 -m ai_starter.main

# Or install in editable mode
pip install -e .
```

**Ollama connection errors**:
- Ensure Ollama is running: `ollama serve`
- Check base_url in config.yaml matches Ollama's address
- Verify model is pulled: `ollama list`

**Missing mission.txt**:
- Agent will refuse to boot without a valid mission.txt
- Copy mission.example.txt and customize it

## Next Steps

1. Edit `mission.txt` with your agent's purpose
2. Add tasks to the queue (see README.md)
3. Run `ai-starter --once` to test
4. Run `ai-starter` for continuous operation
