#!/usr/bin/env bash
# Stress test for the Communication Module.
# Usage: ./run_stress.sh [iterations]   (default 10000)
set -euo pipefail
cd "$(dirname "$0")"

ITERS="${1:-10000}"
ROOT="$(cd ../.. && pwd)"   # GENESIS root
MODULE_DIR="$ROOT/modules/communication"
VENV="$ROOT/.venv_comm"

mkdir -p logs run

if [[ ! -d "$VENV" ]]; then
  echo "[run] creating venv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$MODULE_DIR/requirements.txt" pytest pytest-asyncio
fi

PY="$VENV/bin/python"

# Start node
nohup "$PY" "$MODULE_DIR/node/server.py" >logs/node.log 2>&1 &
echo $! >run/node.pid
echo "[run] node pid=$(cat run/node.pid)"

# Wait for health
for i in {1..40}; do
  if curl -sf http://127.0.0.1:9100/health >/dev/null; then
    echo "[run] node healthy"
    break
  fi
  sleep 0.25
done

# TestMath_B (solver) first
nohup "$PY" test_math_b.py >logs/test_math_b.log 2>&1 &
echo $! >run/test_math_b.pid
echo "[run] TestMath_B pid=$(cat run/test_math_b.pid)"

sleep 1.0   # give B time to register + connect SSE

# TestMath_A (asker)
nohup "$PY" test_math_a.py "$ITERS" >logs/test_math_a.log 2>&1 &
echo $! >run/test_math_a.pid
echo "[run] TestMath_A pid=$(cat run/test_math_a.pid) iters=$ITERS"

echo "[run] tail logs: tail -f $(pwd)/logs/test_math_a.log"
