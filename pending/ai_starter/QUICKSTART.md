# ai_starter - 5-Minute Quickstart

Get your autonomous AI agent running in 5 minutes.

## Prerequisites

- Python 3.10+
- Ollama installed

## Step 1: Install (30 seconds)

```bash
cd ~/ai/GENESIS/ai_starter
pip install -e .
```

## Step 2: Configure Mission (1 minute)

Copy the example and edit:

```bash
cp mission.example.txt mission.txt
nano mission.txt
```

Example mission:
```
IDENTITY: TaskBot
ROLE: Autonomous task executor that breaks down goals into steps
OWNER: Your Name

PRINCIPLES:
- Break tasks into clear, executable steps
- Learn from both successes and failures
- Provide transparent reasoning

CONSTRAINTS:
- Never execute destructive operations without confirmation
- Never expose sensitive data in logs
- Always validate inputs before tool execution
```

## Step 3: Start Ollama (1 minute)

In a separate terminal:

```bash
# Start Ollama server
ollama serve

# In another terminal, pull a model
ollama pull phi3:mini
```

## Step 4: Test Run (1 minute)

Process one task and exit:

```bash
cd ~/ai/GENESIS/ai_starter
python3 -m ai_starter.main --once
```

You should see:
- ✅ Identity loaded
- ✅ Ollama connected
- ✅ Task executed
- ✅ Reflection generated
- ✅ Learnings stored

## Step 5: Run Continuously (30 seconds)

Start the autonomous loop:

```bash
python3 -m ai_starter.main
```

The agent will:
1. Check queue every 30 seconds
2. Pick highest priority task
3. Plan steps using LLM
4. Execute via tools
5. Reflect on results
6. Store learnings
7. Repeat

Press `Ctrl+C` to stop gracefully.

## Adding Tasks

Edit your main.py or create a script:

```python
from ai_starter.core.state import Task, TaskQueue, TaskPriority
from pathlib import Path

# Load existing queue
queue = TaskQueue.load(Path("~/.ai_starter/queue.json").expanduser())

# Add a task
queue.add(Task(
    description="Check disk usage and write report to /tmp/disk_report.txt",
    priority=TaskPriority.high,
))

# Save
queue.save(Path("~/.ai_starter/queue.json").expanduser())
```

## Built-in Tools

Your agent has 3 tools ready:

1. **shell_execute** - Run shell commands
2. **file_read** - Read file contents  
3. **file_write** - Write to files

Example task: "List all Python files in /tmp and save to /tmp/python_files.txt"

## Configuration

Edit `config.yaml` to customize:

```yaml
ollama:
  model: "phi3:mini"  # Change model
  temperature: 0.7    # Creativity (0.0-1.0)

loop:
  interval_seconds: 30  # How often to check queue

data_dir: "~/.ai_starter"  # Where to store data
log_level: "INFO"          # DEBUG for verbose
```

## Monitoring

Logs are JSON (structured):

```bash
# Watch logs in real-time
python3 -m ai_starter.main | jq
```

Check stored data:

```bash
ls ~/.ai_starter/
# memory.db   - SQLite database with memories
# queue.json  - Task queue state
# state.json  - Agent state
```

Query memory:

```bash
sqlite3 ~/.ai_starter/memory.db "SELECT * FROM memories ORDER BY created_at DESC LIMIT 5;"
```

## Troubleshooting

**"Ollama not available"**
- Check: `ollama list` (should show models)
- Ensure: `ollama serve` is running

**"Identity not loaded"**
- Ensure `mission.txt` exists
- Check format: IDENTITY, ROLE, OWNER required

**"Module not found"**
- Run: `pip install -e .` from ai_starter directory

**Tests failing**
```bash
cd ~/ai/GENESIS/ai_starter
PYTHONPATH=. python3 tests/test_core.py
PYTHONPATH=. python3 tests/test_llm.py  
PYTHONPATH=. python3 tests/test_memory.py
```

## Next Steps

1. **Add custom tools**: Edit `ai_starter/tools/registry.py`
2. **Tune prompts**: Edit `ai_starter/llm/prompt_builder.py`
3. **Change behavior**: Edit mission.txt
4. **Monitor learnings**: Query memory.db
5. **Scale up**: Add more tasks to queue

## Example Session

```bash
$ python3 -m ai_starter.main --once

{"event": "starting_agent", "timestamp": "2026-02-15T01:20:00Z"}
{"event": "identity_loaded", "name": "TaskBot", "role": "..."}
{"event": "processing_task", "task_id": "...", "description": "Check system time..."}
{"event": "plan_generated", "num_steps": 2}
{"event": "step_executed", "tool": "shell_execute", "success": true}
{"event": "step_executed", "tool": "file_write", "success": true}
{"event": "reflection_complete", "success": true, "learnings": 1}
{"event": "tick_completed", "duration_ms": 2341}

Task: Check system time and write to /tmp/test.txt
Success: True
Summary: Successfully retrieved system time and wrote to file
```

---

**You're ready!** Your autonomous AI agent is now running and learning from every task it executes.

For more details, see:
- `README.md` - Full documentation
- `INSTALL.md` - Installation guide
- `IMPLEMENTATION_SUMMARY.md` - Architecture details
