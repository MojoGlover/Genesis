# ai_starter — Reusable AI Agent Template

A clean, minimal, working AI agent template. Write a mission → run → agent starts processing tasks and learning.

**Design philosophy**: Ollama-only, SQLite-only, no cloud keys, minimal dependencies.

---

## Quick Start

1. **Edit `mission.txt`** with your agent's identity:
```
IDENTITY: MyAgent
ROLE: Does X, Y, Z
OWNER: Your Name

PRINCIPLES:
- Principle 1
- Principle 2

CONSTRAINTS:
- Must never do X
- Must always verify Y
```

2. **Install dependencies**:
```bash
cd ~/ai/GENESIS/ai_starter
pip install -e .
```

3. **Ensure Ollama is running**:
```bash
ollama serve
ollama pull phi3:mini
```

4. **Run the agent**:
```bash
python main.py
```

Or use `--once` mode for testing:
```bash
python main.py --once
```

---

## Architecture

- **`core/state.py`**: Task queue, priority, retry logic (Pydantic models)
- **`core/identity.py`**: Mission parsing, boot enforcement
- **`core/loop.py`**: Plan → Execute → Reflect autonomous loop
- **`llm/client.py`**: Async Ollama client (httpx)
- **`llm/prompt_builder.py`**: System prompts, planning, reflection
- **`llm/response_parser.py`**: Extract JSON from LLM output
- **`memory/storage.py`**: SQLite + FTS5 for persistent memory
- **`memory/retrieval.py`**: Context search for tasks
- **`tools/registry.py`**: Decorator-based tool registration
- **`tools/executor.py`**: Safe tool execution (timeout, output limits)
- **`improvement/self_eval.py`**: LLM-based task evaluation
- **`improvement/adaptation.py`**: Inject learnings into prompts

---

## Built-in Tools

- `shell_execute(command: str)` — Run shell commands
- `file_read(path: str)` — Read file contents
- `file_write(path: str, content: str)` — Write to file

---

## Configuration

Edit `config.yaml`:
```yaml
ollama:
  base_url: "http://localhost:11434"
  model: "phi3:mini"
  temperature: 0.7
  max_tokens: 2048

loop:
  interval_seconds: 30
  max_retries: 3
  task_timeout_seconds: 300

data_dir: "~/.ai_starter"
log_level: "INFO"
```

Or use environment variables:
```bash
export AI_STARTER_OLLAMA__MODEL=llama3
export AI_STARTER_LOG_LEVEL=DEBUG
```

---

## Testing

Run unit tests:
```bash
python -m pytest tests/ -v
```

Or run individual test files:
```bash
python tests/test_core.py
python tests/test_llm.py
python tests/test_memory.py
```

---

## Data Flow (One Tick)

```
main.py → AgentLoop.tick()
  ├─ TaskQueue.next() → Task
  ├─ retrieve_context(task) → memory search
  ├─ build_plan_prompt(task, tools) → LLM prompt
  ├─ OllamaClient.generate(prompt) → raw plan
  ├─ parse_plan(raw) → list[Step]
  ├─ for each Step:
  │   ├─ ToolExecutor.execute(step) → ToolResult
  │   └─ collect StepResult
  ├─ build_reflect_prompt(task, results) → reflection prompt
  ├─ OllamaClient.generate(reflect) → raw reflection
  ├─ parse_reflection(raw) → Reflection
  ├─ SelfEvaluator.evaluate(tick) → EvalReport
  ├─ memory.store(task_result + learnings)
  └─ TaskQueue.complete(task) or TaskQueue.fail(task)
```

---

## Extending

### Add a custom tool:

```python
from ai_starter.tools.registry import tool

@tool("my_tool", "Does something useful", category="custom")
def my_tool(arg1: str, arg2: int) -> str:
    # Your implementation
    return f"Processed {arg1} with {arg2}"

# Register in main.py:
registry.register("my_tool", "Does something", my_tool, "custom")
```

### Add tasks programmatically:

```python
from ai_starter.core.state import Task, TaskPriority

queue.add(Task(
    description="Your task here",
    priority=TaskPriority.high,
))
```

---

## Verification Checklist

1. ✅ Unit tests pass: `pytest tests/ -v`
2. ✅ Boot test: `python main.py --once` (with Ollama running)
3. ✅ Queue test: Tasks get planned/executed/reflected
4. ✅ Memory test: Second task retrieves learnings from first
5. ✅ No-mission test: Agent refuses to boot without `mission.txt`
6. ✅ No-Ollama test: Agent waits gracefully if Ollama unavailable

---

## Borrowed Patterns

| Pattern | Source | Usage |
|---------|--------|-------|
| Priority queue + retry | Engineer0 `task_queue.py` | `core/state.py` |
| Mission parsing | Engineer0 `mission.py` | `core/identity.py` |
| Async Ollama | GENESIS `providers/ollama.py` | `llm/client.py` |
| Plan/Execute/Reflect | GENESIS `core/agent.py` | `core/loop.py` |
| Tool registry | GENESIS `tools/tool_registry.py` | `tools/registry.py` |
| SQLite memory | GENESIS `storage/memory.py` | `memory/storage.py` |

---

## License

MIT

## 🚀 Enterprise Features

ai_starter now includes enterprise-grade enhancements:

### RAG (Retrieval-Augmented Generation)
- Document indexing and chunking
- FTS5-powered retrieval
- Automatic prompt augmentation
- Context-aware responses

### MCP (Model Context Protocol)
- Connect to MCP servers
- Extended tool ecosystem
- Standard protocol support
- Server discovery

### LangChain/LangGraph Integration
- LangChain-compatible adapters
- Workflow graphs
- Multi-step orchestration
- Execution tracing

### Validators & Verifiers
- Schema validation (Pydantic)
- Output verification
- Safety checks
- Quality metrics

See [ENHANCEMENTS.md](ENHANCEMENTS.md) for detailed documentation.

## Architecture Highlights

✅ **Fully Modular** - Each component is independently usable  
✅ **Pydantic Everywhere** - Type-safe, validated data models  
✅ **RAG-Ready** - Built-in document retrieval and context injection  
✅ **MCP-Compatible** - Standard Model Context Protocol support  
✅ **Framework Agnostic** - Works standalone or with LangChain/LangGraph  
✅ **Production-Ready** - Validators, verifiers, quality checks  

