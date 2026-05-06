#!/usr/bin/env bash
# End-to-end test: math agents communicating through PlugOps SSE transport.
# Usage: ./run_plugops_test.sh [iterations]
set -euo pipefail
cd "$(dirname "$0")"

ITERS="${1:-500}"
PLUGOPS_DIR="/Users/darnieglover/ai/cmptrblk/PlugOps"
VENV="$PLUGOPS_DIR/venv/bin/python"
PLUGOPS_URL="http://127.0.0.1:9000"

mkdir -p logs run

# ── ensure PlugOps is running ─────────────────────────────────────────────
if ! curl -sf "$PLUGOPS_URL/health" >/dev/null 2>&1; then
    echo "[test] starting PlugOps..."
    cd "$PLUGOPS_DIR"
    nohup venv/bin/uvicorn plugops.api.server:app \
        --host 127.0.0.1 --port 9000 --log-level warning \
        > /tmp/plugops_test.log 2>&1 &
    echo $! > /tmp/plugops_test.pid
    cd - >/dev/null
    for i in {1..30}; do
        curl -sf "$PLUGOPS_URL/health" >/dev/null 2>&1 && break
        sleep 0.5
    done
    echo "[test] PlugOps started"
else
    echo "[test] PlugOps already running"
fi

# Install deps if needed
if ! "$VENV" -c "import httpx_sse" 2>/dev/null; then
    "$PLUGOPS_DIR/venv/bin/pip" install --quiet httpx-sse
fi

# ── start TestMath_B ──────────────────────────────────────────────────────
nohup "$VENV" math_agent_b.py "$PLUGOPS_URL" > logs/math_b.log 2>&1 &
echo $! > run/math_b.pid
echo "[test] TestMath_B started (pid=$(cat run/math_b.pid))"
sleep 1.0

# ── start TestMath_A ─────────────────────────────────────────────────────
nohup "$VENV" math_agent_a.py "$ITERS" "$PLUGOPS_URL" > logs/math_a.log 2>&1 &
echo $! > run/math_a.pid
echo "[test] TestMath_A started (pid=$(cat run/math_a.pid)) iters=$ITERS"
echo "[test] waiting for completion..."

# ── wait and report ──────────────────────────────────────────────────────
until grep -q "DONE\|Traceback" logs/math_a.log 2>/dev/null; do sleep 2; done

echo ""
echo "══════════════════════════════════════"
echo " TEST RESULT (Rule 22 — actual output)"
echo "══════════════════════════════════════"
grep -E "DONE|i=[0-9]" logs/math_a.log | tail -5
echo ""
echo "── TestMath_B ──"
tail -3 logs/math_b.log
echo ""
echo "── PlugOps agent list ──"
curl -s "$PLUGOPS_URL/api/v1/agents" | python3 -c "
import sys, json
agents = json.load(sys.stdin)
for a in agents:
    print(f\"  {a.get('name','?'):20} status={a.get('status','?')}\")
" 2>/dev/null || echo "  (could not fetch agent list)"
echo "══════════════════════════════════════"

# cleanup agents
kill "$(cat run/math_b.pid)" 2>/dev/null && echo "[test] TestMath_B stopped"
rm -f run/math_a.pid run/math_b.pid
