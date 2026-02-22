#!/usr/bin/env python3
"""
build_madjanet.py
Builds MadJanet's full training dataset by:
  1. Copying cb_core_brain.jsonl with MadJanet system prompt (Set 1)
  2. Merging Set 1 + Set 2 (assistant function) + Set 3 (Janet personality)
  3. Saving to brain_trainer/training_data/madjanet_full.jsonl
"""

import json
import os
from pathlib import Path

# --- Paths ---
BASE = Path.home() / "ai" / "GENESIS"
CB_CORE_BRAIN = BASE / "cb_core" / "cb_core" / "training" / "data" / "cb_core_brain.jsonl"
MADJANET_DIR  = BASE / "cb_core" / "madjanet" / "training_data"
SET2          = MADJANET_DIR / "set2_assistant_function.jsonl"
SET3          = MADJANET_DIR / "set3_janet_personality.jsonl"
SET1_OUT      = MADJANET_DIR / "set1_cb_core.jsonl"
OUTPUT_DIR    = BASE / "brain_trainer" / "training_data"
OUTPUT        = OUTPUT_DIR / "madjanet_full.jsonl"

MADJANET_SYSTEM = (
    "You are MadJanet, a Computer Black AI personal assistant built by Kris Glover. "
    "Your primary job is delivery route assistant. "
    "Responses are short — Kris is usually driving. "
    "Warm, eager, slightly weird, no-nonsense. Not a robot."
)

def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  WARNING: skipped malformed line {i} in {path.name}: {e}")
    return records

def restamp_system(records: list[dict], system_prompt: str) -> list[dict]:
    """Replace system message in every record with MadJanet system prompt."""
    out = []
    for rec in records:
        msgs = rec.get("messages", [])
        new_msgs = []
        for msg in msgs:
            if msg["role"] == "system":
                new_msgs.append({"role": "system", "content": system_prompt})
            else:
                new_msgs.append(msg)
        out.append({"messages": new_msgs})
    return out

def write_jsonl(records: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

def main():
    print("=" * 55)
    print("  MadJanet Training Data Builder")
    print("  Computer Black / Kris Glover")
    print("=" * 55)

    # --- SET 1: cb_core_brain with MadJanet system prompt ---
    print(f"\nLoading cb_core_brain from:\n  {CB_CORE_BRAIN}")
    if not CB_CORE_BRAIN.exists():
        print(f"  ERROR: {CB_CORE_BRAIN} not found. Skipping Set 1.")
        set1 = []
    else:
        raw = load_jsonl(CB_CORE_BRAIN)
        set1 = restamp_system(raw, MADJANET_SYSTEM)
        write_jsonl(set1, SET1_OUT)
        print(f"  Set 1 written: {len(set1)} samples → {SET1_OUT.name}")

    # --- SET 2: Personal assistant + delivery function ---
    print(f"\nLoading Set 2 from:\n  {SET2}")
    if not SET2.exists():
        print(f"  ERROR: {SET2} not found.")
        set2 = []
    else:
        set2 = load_jsonl(SET2)
        print(f"  Set 2 loaded: {len(set2)} samples")

    # --- SET 3: Janet personality patterns ---
    print(f"\nLoading Set 3 from:\n  {SET3}")
    if not SET3.exists():
        print(f"  ERROR: {SET3} not found.")
        set3 = []
    else:
        set3 = load_jsonl(SET3)
        print(f"  Set 3 loaded: {len(set3)} samples")

    # --- MERGE ---
    all_records = set1 + set2 + set3
    write_jsonl(all_records, OUTPUT)

    # --- REPORT ---
    print("\n" + "=" * 55)
    print("  BUILD COMPLETE")
    print("=" * 55)
    print(f"  Set 1 (CB Core, MadJanet prompt): {len(set1):>4} samples")
    print(f"  Set 2 (Assistant + Delivery):     {len(set2):>4} samples")
    print(f"  Set 3 (Janet Personality):        {len(set3):>4} samples")
    print(f"  {'─' * 38}")
    print(f"  TOTAL:                            {len(all_records):>4} samples")
    print(f"\n  Output: {OUTPUT}")
    print("\nMADJANET_DONE")

if __name__ == "__main__":
    main()
