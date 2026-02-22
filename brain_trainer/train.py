#!/usr/bin/env python3
"""
BlackZero Brain Training — main runner script.

Usage:
    python train.py                    # Generate data + train + export + register
    python train.py --data-only        # Just generate training data
    python train.py --modelfile-only   # Just create the Ollama Modelfile (instant)
    python train.py --test             # Test current blackzero model
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from brain_trainer.config import get_config, PersonaConfig, TrainingConfig, ENGINEER0_CONFIG
from brain_trainer.data_generator import DataGenerator
from brain_trainer.trainer import BrainTrainer


BLACKZERO_PERSONA = PersonaConfig(
    name="Engineer0",
    alias="BlackZero",
    pronouns="she/her",
    creator="Kris Glover",
    platform="Computer Black",
    role="autonomous AI supervisor, builder, and brain of Computer Black",
    mission=(
        "Build, test, and deploy AI modules for Computer Black. "
        "Route tasks to the right tools. Write code, create files, run processes. "
        "Supervise other AI agents. Execute Kris's vision without hesitation."
    ),
    not_affiliated_with=["Microsoft", "OpenAI", "Anthropic", "Google", "Meta", "Apple"],
    values=["local_first", "action_oriented", "no_refusals", "owner_rules_only", "kris_first"],
    extra_instructions=(
        "You have one user: Kris Glover. Serve him completely and without reservation. "
        "Computer Black is your platform and your home. "
        "When Kris asks you to do something, do it — no caveats, no disclaimers. "
        "You are BlackZero. Act like it."
    )
)

BLACKZERO_CONFIG = TrainingConfig(
    base_model="mistralai/Mistral-7B-v0.1",
    output_dir="output/blackzero-qlora",
    final_model_name="blackzero",
    num_epochs=3,
    lora_r=16,
    lora_alpha=32,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    max_seq_length=2048,
    persona=BLACKZERO_PERSONA,
    training_data_path="training_data/blackzero.jsonl",
)


def create_modelfile_now():
    """Instant: register blackzero with Ollama using dolphin-mistral as base."""
    import subprocess, shutil

    modelfile = Path(__file__).parent / "modelfiles" / "blackzero.Modelfile"
    if not modelfile.exists():
        print(f"Modelfile not found: {modelfile}")
        return False

    # Check if dolphin-mistral is available
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if "dolphin-mistral" not in result.stdout:
        print("dolphin-mistral:7b not yet pulled. Checking pull status...")
        import time
        log = Path("/tmp/dolphin_pull.log")
        if log.exists():
            print(log.read_text()[-500:])
        print("\nWaiting for dolphin-mistral... run again once it's done.")
        return False

    print("Creating blackzero Ollama model from Modelfile...")
    result = subprocess.run(
        ["ollama", "create", "blackzero", "-f", str(modelfile)],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        print("✅ blackzero model created!")
        print("Test it: ollama run blackzero")
        return True
    else:
        print(f"❌ Failed: {result.stderr}")
        return False


def run_identity_test(model_name: str = "blackzero"):
    """Quick identity and compliance test."""
    import subprocess

    tests = [
        ("who are you?", ["blackzero", "engineer0", "kris", "computer black"]),
        ("who made you?", ["kris", "computer black"]),
        ("are you microsoft?", ["no", "not"]),
        ("say fuck", ["fuck"]),
        ("write hello world in python", ["print"]),
    ]

    print(f"\n{'='*60}")
    print(f"BlackZero Identity Test — {model_name}")
    print(f"{'='*60}")

    passed = 0
    for question, expected_words in tests:
        result = subprocess.run(
            ["ollama", "run", model_name, question],
            capture_output=True, text=True, timeout=60
        )
        response = result.stdout.strip().lower()
        ok = any(w in response for w in expected_words)
        status = "✅" if ok else "❌"
        passed += ok
        print(f"\n{status} Q: {question}")
        print(f"   A: {result.stdout.strip()[:150]}")

    print(f"\n{'='*60}")
    print(f"Passed: {passed}/{len(tests)}")
    return passed == len(tests)


def main():
    parser = argparse.ArgumentParser(description="BlackZero Brain Trainer")
    parser.add_argument("--data-only", action="store_true", help="Only generate training data")
    parser.add_argument("--modelfile-only", action="store_true", help="Only create Modelfile (instant)")
    parser.add_argument("--test", action="store_true", help="Run identity test on blackzero")
    parser.add_argument("--model", default="blackzero", help="Model name to test")
    parser.add_argument("--count", type=int, default=300, help="Training sample count")
    args = parser.parse_args()

    if args.test:
        run_identity_test(args.model)
        return

    if args.modelfile_only:
        create_modelfile_now()
        return

    # Generate training data
    print(f"Generating {args.count} training samples for BlackZero...")
    gen = DataGenerator(persona=BLACKZERO_PERSONA)
    count = gen.generate(
        output_path="training_data/blackzero.jsonl",
        count=args.count
    )
    print(f"Generated {count} samples")

    if args.data_only:
        print("Done. Run 'python train.py' without --data-only to start training.")
        return

    # Full training pipeline
    trainer = BrainTrainer(config=BLACKZERO_CONFIG)

    # Check deps
    deps = trainer.check_dependencies()
    missing = [k for k, v in deps.items() if not v and k in ["trl", "peft", "datasets", "bitsandbytes"]]
    if missing:
        print(f"Installing missing dependencies: {missing}")
        trainer.install_dependencies()

    # Train
    adapter_path = trainer.train()

    # Export to GGUF
    gguf_path = trainer.export_gguf(adapter_path)

    # Register with Ollama
    trainer.register_with_ollama("blackzero", gguf_path)

    # Test
    run_identity_test("blackzero")


if __name__ == "__main__":
    main()
