# Rasa Module

Conversational AI module with Rasa NLU + Ollama LLM backend.

## Features

- **Rasa NLU**: Intent classification, entity extraction
- **Ollama Backend**: Local LLM for dialogue generation
- **PlugOps Ready**: Can register as agent
- **Standalone**: Works independently or integrated

## Architecture

```
rasa_module/
├── nlu/              # Rasa NLU config & training data
├── actions/          # Custom actions
├── models/           # Trained models
├── ollama_policy/    # Ollama-based dialogue policy
└── bridge/           # PlugOps integration
```

## Usage

Standalone:
```bash
cd ~/ai/GENESIS/rasa_module
./launcher.sh
```

Integrated with Engineer0:
```python
from rasa_module import RasaAgent
agent = RasaAgent()
```

## Development Status

- [ ] NLU configuration
- [ ] Ollama policy
- [ ] Custom actions
- [ ] PlugOps bridge
- [ ] Testing suite
- [ ] Engineer0 integration
