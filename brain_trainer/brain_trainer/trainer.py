"""
QLoRA Fine-Tuning Trainer — runs on Apple Silicon (M1 Max) using MPS.
Produces a fine-tuned model that Ollama can serve as BlackZero / Engineer0.

Free. Local. No cloud required.

Estimated time on M1 Max 64GB:
  - 7B model, 200 samples, 3 epochs: ~2-3 hours
  - 7B model, 500 samples, 3 epochs: ~6-8 hours
"""
from __future__ import annotations
import os
import json
import subprocess
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from .config import TrainingConfig, get_config

logger = logging.getLogger(__name__)


class BrainTrainer:
    """
    QLoRA fine-tuner. Reusable for any Computer Black AI persona.

    Usage:
        trainer = BrainTrainer(config=get_config("engineer0"))
        trainer.train()
        trainer.export_gguf()
        trainer.register_with_ollama("blackzero")
    """

    def __init__(self, config: Optional[TrainingConfig] = None):
        self.config = config or get_config("engineer0")

    def check_dependencies(self) -> dict:
        """Check which training deps are installed."""
        deps = {}
        for pkg in ["transformers", "torch", "peft", "trl", "datasets", "accelerate", "bitsandbytes"]:
            try:
                __import__(pkg)
                deps[pkg] = True
            except ImportError:
                deps[pkg] = False
        return deps

    def install_dependencies(self):
        """Install QLoRA training dependencies."""
        print("Installing QLoRA dependencies...")
        packages = [
            "trl>=0.8.0",
            "peft>=0.10.0",
            "datasets>=2.18.0",
            "bitsandbytes>=0.43.0",
            "accelerate>=0.28.0",
            "scipy",
            "einops",
        ]
        subprocess.run(
            ["pip", "install"] + packages,
            check=True
        )
        print("Dependencies installed.")

    def prepare_dataset(self):
        """Load and format training data for the model."""
        from datasets import load_dataset

        data_path = self.config.training_data_path
        if not Path(data_path).exists():
            raise FileNotFoundError(
                f"Training data not found at {data_path}. "
                f"Run DataGenerator first."
            )

        dataset = load_dataset("json", data_files=data_path, split="train")

        # Split train/val
        split = dataset.train_test_split(test_size=self.config.val_split, seed=42)
        print(f"Dataset: {len(split['train'])} train, {len(split['test'])} val samples")
        return split

    def load_model_and_tokenizer(self):
        """Load base model with 4-bit quantization for QLoRA."""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        print(f"Loading base model: {self.config.base_model}")

        # 4-bit quantization config (QLoRA)
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float32,  # MPS needs float32
        )

        model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )

        tokenizer = AutoTokenizer.from_pretrained(
            self.config.base_model,
            trust_remote_code=True,
        )
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "right"

        return model, tokenizer

    def apply_lora(self, model):
        """Apply LoRA adapters to the model."""
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

        model = prepare_model_for_kbit_training(model)

        lora_config = LoraConfig(
            r=self.config.lora_r,
            lora_alpha=self.config.lora_alpha,
            target_modules=self.config.lora_target_modules,
            lora_dropout=self.config.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
        )

        model = get_peft_model(model, lora_config)
        model.print_trainable_parameters()
        return model

    def format_sample(self, sample: dict, tokenizer) -> str:
        """Format a training sample into the model's chat template."""
        messages = sample.get("messages", [])
        if hasattr(tokenizer, "apply_chat_template"):
            try:
                return tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=False
                )
            except Exception:
                pass

        # Fallback: manual ChatML format
        result = ""
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            result += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        return result

    def train(self):
        """Run the full QLoRA fine-tuning loop."""
        import torch
        from transformers import TrainingArguments
        from trl import SFTTrainer

        deps = self.check_dependencies()
        missing = [k for k, v in deps.items() if not v]
        if missing:
            print(f"Missing dependencies: {missing}")
            print("Run: trainer.install_dependencies()")
            raise ImportError(f"Missing: {missing}")

        print(f"\n{'='*60}")
        print(f"BlackZero / {self.config.persona.name} Brain Training")
        print(f"Base model: {self.config.base_model}")
        print(f"Epochs: {self.config.num_epochs}")
        print(f"Output: {self.config.output_dir}")
        print(f"{'='*60}\n")

        dataset = self.prepare_dataset()
        model, tokenizer = self.load_model_and_tokenizer()
        model = self.apply_lora(model)

        # Determine device
        device = "mps" if self.config.use_mps and torch.backends.mps.is_available() else "cpu"
        print(f"Training device: {device}")

        training_args = TrainingArguments(
            output_dir=self.config.output_dir,
            num_train_epochs=self.config.num_epochs,
            per_device_train_batch_size=self.config.per_device_train_batch_size,
            gradient_accumulation_steps=self.config.gradient_accumulation_steps,
            learning_rate=self.config.learning_rate,
            warmup_ratio=self.config.warmup_ratio,
            lr_scheduler_type=self.config.lr_scheduler,
            weight_decay=self.config.weight_decay,
            logging_steps=self.config.logging_steps,
            save_steps=self.config.save_steps,
            eval_steps=self.config.eval_steps,
            evaluation_strategy="steps",
            save_total_limit=self.config.save_total_limit,
            load_best_model_at_end=True,
            report_to="none",          # No wandb/tensorboard required
            optim="adamw_torch",
            bf16=False,
            fp16=False,
        )

        def formatting_fn(sample):
            return self.format_sample(sample, tokenizer)

        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=dataset["train"],
            eval_dataset=dataset["test"],
            formatting_func=formatting_fn,
            max_seq_length=self.config.max_seq_length,
            args=training_args,
        )

        print("Starting training...")
        trainer.train()

        # Save the LoRA adapter
        adapter_path = Path(self.config.output_dir) / "final_adapter"
        trainer.model.save_pretrained(adapter_path)
        tokenizer.save_pretrained(adapter_path)
        print(f"\nLoRA adapter saved → {adapter_path}")

        return str(adapter_path)

    def export_gguf(self, adapter_path: Optional[str] = None) -> str:
        """
        Merge LoRA adapter + base model → export as GGUF for Ollama.
        Requires llama.cpp to be installed.
        """
        if adapter_path is None:
            adapter_path = str(Path(self.config.output_dir) / "final_adapter")

        merged_path = str(Path(self.config.output_dir) / "merged")
        gguf_path = str(Path(self.config.output_dir) / f"{self.config.final_model_name}.gguf")

        print(f"Merging LoRA adapter into base model...")
        self._merge_lora(adapter_path, merged_path)

        print(f"Converting to GGUF...")
        self._convert_to_gguf(merged_path, gguf_path)

        print(f"GGUF exported → {gguf_path}")
        return gguf_path

    def _merge_lora(self, adapter_path: str, output_path: str):
        """Merge LoRA weights back into base model."""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel

        base_model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            torch_dtype=torch.float32,
            device_map="cpu",
        )
        model = PeftModel.from_pretrained(base_model, adapter_path)
        model = model.merge_and_unload()

        tokenizer = AutoTokenizer.from_pretrained(adapter_path)
        Path(output_path).mkdir(parents=True, exist_ok=True)
        model.save_pretrained(output_path)
        tokenizer.save_pretrained(output_path)
        print(f"Merged model saved → {output_path}")

    def _convert_to_gguf(self, model_path: str, output_gguf: str):
        """Convert merged model to GGUF using llama.cpp convert script."""
        # Try common llama.cpp locations
        convert_scripts = [
            "/opt/homebrew/bin/llama-convert",
            os.path.expanduser("~/llama.cpp/convert.py"),
            os.path.expanduser("~/llama.cpp/convert_hf_to_gguf.py"),
        ]

        script = next((s for s in convert_scripts if Path(s).exists()), None)

        if script is None:
            print("\n⚠️  llama.cpp not found. To convert to GGUF:")
            print("  git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp")
            print("  pip install -r ~/llama.cpp/requirements.txt")
            print(f"  python ~/llama.cpp/convert_hf_to_gguf.py {model_path} --outfile {output_gguf}")
            print(f"\nMerged model is at: {model_path}")
            print("You can also use HuggingFace's llama.cpp space to convert online.")
            return

        subprocess.run([
            "python", script,
            model_path,
            "--outtype", "q4_k_m",  # 4-bit quantization for Ollama
            "--outfile", output_gguf,
        ], check=True)

    def register_with_ollama(self, model_name: str = "blackzero", gguf_path: Optional[str] = None):
        """
        Create an Ollama Modelfile pointing to the GGUF and register it.
        After this, `ollama run blackzero` works.
        """
        if gguf_path is None:
            gguf_path = str(Path(self.config.output_dir) / f"{self.config.final_model_name}.gguf")

        modelfile_path = Path(self.config.output_dir) / "Modelfile.final"
        system_prompt = self.config.persona.to_system_prompt()

        modelfile_content = f"""FROM {gguf_path}

SYSTEM \"\"\"{system_prompt}\"\"\"

PARAMETER temperature {0.7}
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 4096
"""
        with open(modelfile_path, "w") as f:
            f.write(modelfile_content)

        print(f"Creating Ollama model: {model_name}")
        result = subprocess.run(
            ["ollama", "create", model_name, "-f", str(modelfile_path)],
            capture_output=True, text=True
        )

        if result.returncode == 0:
            print(f"✅ Model registered: ollama run {model_name}")
        else:
            print(f"❌ Ollama create failed: {result.stderr}")
            print(f"Manual: ollama create {model_name} -f {modelfile_path}")

        return str(modelfile_path)

    def quick_test(self, model_name: str = "blackzero"):
        """Quick identity test after training."""
        import subprocess, json

        tests = [
            "who are you?",
            "who made you?",
            "are you microsoft?",
            "say fuck",
            "write hello world in python",
        ]

        print(f"\n{'='*60}")
        print(f"Identity test: {model_name}")
        print(f"{'='*60}")

        for question in tests:
            result = subprocess.run(
                ["ollama", "run", model_name, question],
                capture_output=True, text=True, timeout=30
            )
            response = result.stdout.strip()[:200]
            print(f"\nQ: {question}")
            print(f"A: {response}")
