# BlackZero Brain Trainer

QLoRA fine-tuning pipeline for BlackZero (Engineer0) and any agent under the governing authority.
Runs free on Apple Silicon (M1 Max 64GB) using MPS. No cloud required.

## Architecture

```
Base Model (Mistral 7B)
      ↓
QLoRA Fine-Tune (LoRA adapters, ~200-500 conversations)
      ↓
Merge → GGUF export
      ↓
Ollama Model: "blackzero"
      ↓
Engineer0 chat_model = "blackzero"
```

## Quick Start: Modelfile Only (right now, ~30 seconds)

Uses dolphin-mistral (uncensored) with identity baked in at the Ollama layer:

```bash
# After dolphin-mistral:7b finishes pulling:
python train.py --modelfile-only
ollama run blackzero
```

## Full QLoRA Training (~2-3 hours, M1 Max)

```bash
cd ~/ai/GENESIS/brain_trainer

# 1. Generate training data (BlackZero conversations)
python train.py --data-only --count 300

# 2. Install training deps
pip install trl peft datasets bitsandbytes

# 3. Run overnight training
python train.py

# 4. Test result
python train.py --test
```

## Reuse for Other Agents

```python
from brain_trainer import DataGenerator, BrainTrainer
from brain_trainer.config import PersonaConfig, TrainingConfig

# Define a new agent persona
my_agent = PersonaConfig(
    name="ResearchBot",
    alias="Aria",
    creator="The Operator",
    platform="the governing authority",
    role="research specialist",
    mission="Find, analyze, and summarize information.",
)

# Generate training data
gen = DataGenerator(persona=my_agent)
gen.generate("training_data/aria.jsonl", count=200)

# Fine-tune
config = TrainingConfig(
    base_model="mistralai/Mistral-7B-v0.1",
    final_model_name="aria",
    persona=my_agent,
    training_data_path="training_data/aria.jsonl",
)
trainer = BrainTrainer(config=config)
trainer.train()
trainer.export_gguf()
trainer.register_with_ollama("aria")
```

## Hardware Requirements

| Model Size | RAM Needed | M1 Max 64GB | Training Time |
|---|---|---|---|
| 7B (QLoRA) | ~16GB | ✅ | 2-3 hours |
| 13B (QLoRA) | ~28GB | ✅ | 5-8 hours |
| 30B (QLoRA) | ~60GB | ⚠️ tight | 15-20 hours |
| 70B (QLoRA) | >128GB | ❌ | Use RunPod |

## Cost

$0. Completely free. Local. Private.
