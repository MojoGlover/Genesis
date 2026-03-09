#!/usr/bin/env python3
"""
Build Engineer0's training data by merging:
  Set 1: cb_core_brain.jsonl    (85 samples — generic CB brain)
  Set 2: engineer0_function.jsonl (42 samples — Engineer0 specialization)

Output: training_data/engineer0_full.jsonl  (127 samples, ready to train)
"""
from pathlib import Path
import shutil

GENESIS = Path("~/ai/GENESIS").expanduser()
CB_CORE_DATA = GENESIS / "cb_core/cb_core/training/data"
TRAIN_DATA   = GENESIS / "brain_trainer/training_data"
TRAIN_DATA.mkdir(exist_ok=True)

set1 = CB_CORE_DATA / "cb_core_brain.jsonl"
set2 = CB_CORE_DATA / "engineer0_function.jsonl"
merged = TRAIN_DATA / "engineer0_full.jsonl"

lines = []
for src in [set1, set2]:
    lines.extend(l for l in src.read_text().splitlines() if l.strip())

merged.write_text("\n".join(lines) + "\n")

print(f"Set 1 (CB core):     {sum(1 for l in set1.read_text().splitlines() if l.strip())} samples")
print(f"Set 2 (Engineer0):   {sum(1 for l in set2.read_text().splitlines() if l.strip())} samples")
print(f"Merged total:        {len(lines)} samples")
print(f"Output: {merged}")
print()
print("To train: cd ~/ai/GENESIS/brain_trainer && python3 train.py --data engineer0_full.jsonl")
