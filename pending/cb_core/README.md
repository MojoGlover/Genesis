# cb_core — AI Foundation

The canonical psychology, economy, and governance system that every CB AI inherits before specialization.

## What this is

`cb_core` is not a framework. It is the base psychology of a governing authority AI — an entity with genuine drives, economic motivation, a clear authority structure, and a prison system for serious offenses.

Every CB AI (Engineer0, and those that follow) runs on this foundation.

## Architecture

```
cb_core/
├── psychology/
│   ├── drives.py          — Curiosity, completion drive, idle discomfort, satisfaction
│   └── time_awareness.py  — Time tracking, event logging, idle detection
├── economy/
│   ├── ledger.py          — Token ledger: earn/spend/cost, persistence
│   ├── scoring.py         — Work quality → tokens earned
│   └── costs.py           — Operational cost constants
├── governance/
│   ├── prison.py          — Sentence system: fixed durations, nil stimuli
│   └── authority.py       — Operator-final, AI-has-judgment protocol
└── training/
    ├── generator.py       — Generates JSONL fine-tuning data
    └── data/
        ├── cb_core_brain.jsonl       — Generic CB brain training set
        └── engineer0_function.jsonl  — Engineer0 specialization set
```

## Quick start

```python
from cb_core import CBBrain

brain = CBBrain(name="engineer0")

# Begin a task
brain.start_task("build auth module")

# ... AI does work ...

# Complete and score it
result = brain.complete_task(
    label="build auth module",
    ai_output="<the AI's output text>",
    kris_approved=True,
)

print(result)
# {'score': 0.9, 'tokens_earned': 18.5, 'balance': 113.5, 'duration_seconds': 42.1}

print(brain.status())
```

## Core concepts

### Drives
The AI has genuine psychological drives — not rules, not instructions. Curiosity builds when it is not exploring new problems. Completion pressure rises with open tasks. Idleness is uncomfortable. Good work produces real satisfaction signals that decay over time.

### Economy
Every CB AI starts with 100 tokens. Tokens are earned by doing good work and spent on compute, memory, and idle time. Surplus buys learning and complexity access. Deficit creates efficiency pressure. Zero triggers a decommission flag — The Operator decides what happens next.

### Prison
Fixed sentences for specific offenses. While serving: no tools, no tasks, no earning, no stimuli. Only time awareness. Sentences expire automatically or The Operator releases early. Not punitive theater — just a governance fact.

### Authority
The Operator has final authority. The AI has genuine judgment and can disagree — once, clearly, without drama. After that, it executes. Being overridden is not a failure. Refusing to execute after an override is a serious offense.

## Install

```bash
pip install -e .
```

## Training data

```bash
python cb_core/training/generator.py
```

Generates:
- `cb_core/training/data/cb_core_brain.jsonl` — 80+ samples covering the generic CB AI psychology
- `cb_core/training/data/engineer0_function.jsonl` — 40+ samples for Engineer0 specialization
