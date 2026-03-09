"""
Brain Trainer — QLoRA fine-tuning pipeline for Engineer0 and any Computer Black AI.

Produces a custom .gguf model file that Ollama can serve.
Runs entirely free on Apple Silicon (M1 Max 64GB) using MPS.

Usage:
    from brain_trainer import BrainTrainer, DataGenerator

    # Generate training data
    gen = DataGenerator(persona="engineer0")
    gen.generate(output="training_data/engineer0.jsonl", count=200)

    # Fine-tune
    trainer = BrainTrainer(config="configs/engineer0.yaml")
    trainer.train()
    trainer.export_gguf()
    trainer.register_with_ollama("engineer0-ft")
"""
from .trainer import BrainTrainer
from .data_generator import DataGenerator
from .config import TrainingConfig, PersonaConfig

__all__ = ["BrainTrainer", "DataGenerator", "TrainingConfig", "PersonaConfig"]
