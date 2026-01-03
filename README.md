# GENESIS v0.4
**Modular AI System Template** - Local-first, extensible, production-ready

## What is GENESIS?
A template AI system that serves as a foundation for building specialized AI agents. Features multi-provider support, memory, semantic search, and a tool system.

## Features
✅ **Multi-Provider Support** - Ollama (local), Claude, GPT-4, Gemini  
✅ **Smart Routing** - Automatically uses fast/powerful models based on complexity  
✅ **Memory System** - SQLite for conversations + Qdrant for semantic search  
✅ **Tool System** - Web search, file operations, vision analysis  
✅ **Gradio Interface** - Clean chat UI with status indicators  
✅ **FastAPI Backend** - REST API for programmatic access  

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt --break-system-packages
```

### 2. Start Backend
```bash
uvicorn app:app --reload
```

### 3. Start Interface
```bash
python3 interface.py
```
Open http://localhost:7860

### 4. Test Memory
```bash
curl -X POST http://localhost:8000/ai \
  -H "Content-Type: application/json" \
  -d '{"prompt": "My name is X"}'
```

## Architecture
```
GENESIS/
├── core/
│   ├── providers/       # AI model providers (Ollama, Claude, etc)
│   ├── storage/         # Memory (SQLite + Qdrant vector DB)
│   ├── tools/           # Web search, file ops, vision
│   ├── intelligence/    # Agents, RAG (future)
│   └── orchestration/   # LangGraph workflows (future)
├── api/                 # FastAPI routes
├── interface.py         # Gradio chat UI
└── config.yaml          # System configuration
```

## Configuration

Edit `config.yaml` to change:
- Model preferences (local vs cloud)
- Routing thresholds
- API keys
- Database paths

## Next Steps

1. **Add more tools** - Follow pattern in `core/tools/`
2. **Build agents** - Use intelligence layer for multi-step reasoning
3. **Deploy** - Add Docker/cloud deployment
4. **Extend** - This is a template - make it yours!

## Documentation
- [Architecture Details](ARCHITECTURE.md)
- [Setup Guide](SETUP.md)
- [Adding Tools](docs/ADDING_TOOLS.md)
- [Session Log](CHANGELOG.md)
