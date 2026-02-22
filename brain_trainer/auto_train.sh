#!/bin/bash
# auto_train.sh — Smart nightly BlackZero trainer
# Uses engineer0_full.jsonl (cb_core + engineer0 specialization)
# Auto-approves all samples before training

TRAIN_DIR="$HOME/ai/GENESIS/brain_trainer"
LOG_FILE="$TRAIN_DIR/logs/auto_train.log"
STAMP_FILE="$TRAIN_DIR/logs/last_trained.txt"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
GENESIS="$HOME/ai/GENESIS"

mkdir -p "$TRAIN_DIR/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== Auto-train check ==="

# 1. Skip if already trained today
TODAY=$(date '+%Y-%m-%d')
if [ -f "$STAMP_FILE" ]; then
    LAST=$(cat "$STAMP_FILE")
    if [ "$LAST" = "$TODAY" ]; then
        log "Already trained today ($TODAY). Skipping."
        exit 0
    fi
fi

# 2. Skip if on battery
POWER=$(pmset -g ps 2>/dev/null | head -1)
if echo "$POWER" | grep -q "Battery Power"; then
    log "On battery power. Skipping."
    exit 0
fi

# 3. Rebuild merged training data from cb_core + engineer0 sets
log "Rebuilding engineer0_full.jsonl from cb_core + engineer0 sets..."
$PYTHON "$GENESIS/brain_trainer/build_engineer0.py" >> "$LOG_FILE" 2>&1

# 4. Auto-approve all samples in engineer0_full.jsonl
log "Auto-approving all training samples..."
$PYTHON -c "
import json
from pathlib import Path

data_file = Path('$TRAIN_DIR/training_data/engineer0_full.jsonl')
lines = [l for l in data_file.read_text().splitlines() if l.strip()]
approved = []
for line in lines:
    sample = json.loads(line)
    sample['approved'] = True
    approved.append(json.dumps(sample))

data_file.write_text('\n'.join(approved) + '\n')
print(f'Auto-approved {len(approved)} samples')
" >> "$LOG_FILE" 2>&1

# 5. Install deps if missing
$PYTHON -c "import trl" 2>/dev/null || {
    log "Installing training deps..."
    pip3 install trl peft bitsandbytes datasets transformers accelerate --quiet
}

# 6. Run training
log "Starting training on engineer0_full.jsonl..."
cd "$TRAIN_DIR"
$PYTHON train.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$TODAY" > "$STAMP_FILE"
    log "✅ Training complete. BlackZero updated."
else
    log "❌ Training failed (exit $EXIT_CODE). Check log for details."
fi
