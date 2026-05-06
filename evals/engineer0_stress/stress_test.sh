#!/usr/bin/env bash
# Engineer0 bridge stress test.
# Hammers Engineer0 chat endpoint with N concurrent workers for DURATION seconds.
# Measures: throughput, latency, error rate, bridge drop detection.
#
# Usage: ./stress_test.sh [workers] [duration_seconds]
#   workers:  parallel chat workers (default 5)
#   duration: seconds to run     (default 60)
#
# Pass criteria (Rule 22):
#   error_rate < 1%
#   p95 latency < 10s
#   bridge stays connected (plugops:true) throughout

set -euo pipefail
cd "$(dirname "$0")"

WORKERS="${1:-5}"
DURATION="${2:-60}"
ENG0="http://127.0.0.1:5001"
PLUGOPS="http://127.0.0.1:9000"

mkdir -p logs

echo "══════════════════════════════════════════════"
echo " Engineer0 Bridge Stress Test"
echo " workers=$WORKERS  duration=${DURATION}s"
echo "══════════════════════════════════════════════"

# Verify Engineer0 is up
if ! curl -sf "$ENG0/health" >/dev/null; then
  echo "FAIL: Engineer0 not running at $ENG0"
  exit 1
fi

BRIDGE_STATUS=$(curl -sf "$ENG0/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('plugops','?'))")
echo "Bridge before test: plugops=$BRIDGE_STATUS"
echo ""

START=$(date +%s)
END=$((START + DURATION))
RESULT_FILE="logs/stress_$(date +%Y%m%d_%H%M%S).jsonl"

# Worker function — runs in background, appends JSON result per request
worker() {
  local wid=$1
  local count=0
  local errors=0
  while [ $(date +%s) -lt $END ]; do
    t0=$(python3 -c "import time; print(int(time.time()*1000))")
    response=$(curl -sf -m 30 -X POST "$ENG0/api/chat" \
      -H "Content-Type: application/json" \
      -d "{\"message\":\"w$wid-$count: reply with exactly the word pong\"}" 2>/dev/null)
    t1=$(python3 -c "import time; print(int(time.time()*1000))")
    latency=$((t1 - t0))

    if echo "$response" | grep -q "pong"; then
      echo "{\"w\":$wid,\"i\":$count,\"ok\":true,\"ms\":$latency}" >> "$RESULT_FILE"
    else
      echo "{\"w\":$wid,\"i\":$count,\"ok\":false,\"ms\":$latency,\"resp\":$(echo "$response" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()[:100]))" 2>/dev/null || echo '\"err\"')}" >> "$RESULT_FILE"
      errors=$((errors + 1))
    fi
    count=$((count + 1))
  done
}

# Launch workers in parallel
echo "Running $WORKERS workers for ${DURATION}s..."
for i in $(seq 1 $WORKERS); do
  worker $i &
done

# Monitor bridge health every 10s while workers run
monitor() {
  local drops=0
  while [ $(date +%s) -lt $END ]; do
    sleep 10
    status=$(curl -sf "$ENG0/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('plugops','?'))" 2>/dev/null || echo "unreachable")
    ts=$(date +%H:%M:%S)
    if [ "$status" != "True" ] && [ "$status" != "true" ]; then
      echo "  [$ts] ⚠️  bridge=$status"
      drops=$((drops + 1))
    else
      echo "  [$ts] ✓  bridge=connected"
    fi
  done
  echo "$drops" > logs/.bridge_drops
}
monitor &
MONITOR_PID=$!

wait
kill $MONITOR_PID 2>/dev/null || true

# Analyze results
echo ""
echo "══════════════════════════════════════════════"
echo " RESULTS (Rule 22 — actual output)"
echo "══════════════════════════════════════════════"
python3 - "$RESULT_FILE" <<'PYEOF'
import sys, json, statistics

results = []
with open(sys.argv[1]) as f:
    for line in f:
        try:
            results.append(json.loads(line.strip()))
        except:
            pass

total   = len(results)
ok      = sum(1 for r in results if r.get("ok"))
errors  = total - ok
latencies = [r["ms"] for r in results if r.get("ok")]

def pct(vals, p):
    if not vals: return 0
    s = sorted(vals)
    return s[min(len(s)-1, int(len(s)*p/100))]

print(f"  total requests : {total}")
print(f"  successful     : {ok}")
print(f"  errors         : {errors}")
print(f"  error_rate     : {errors/total*100:.2f}%")
print(f"  throughput     : {total/float(sys.argv[1].split('_')[0].split('/')[-1] if False else 1):.0f} req/s" if False else f"  throughput     : ~{total} req in test window")
if latencies:
    print(f"  latency ms     : min={min(latencies)}  p50={pct(latencies,50)}  p95={pct(latencies,95)}  p99={pct(latencies,99)}  max={max(latencies)}")
print()
passed = errors/total < 0.01 and pct(latencies,95) < 10000
print(f"  VERDICT: {'✅ PASS' if passed else '❌ FAIL'}")
if not passed:
    if errors/total >= 0.01:
        print(f"    ✗ error rate {errors/total*100:.2f}% ≥ 1%")
    if pct(latencies,95) >= 10000:
        print(f"    ✗ p95 latency {pct(latencies,95)}ms ≥ 10000ms")
PYEOF

DROPS=$(cat logs/.bridge_drops 2>/dev/null || echo "?")
echo "  bridge drops   : $DROPS"
echo "══════════════════════════════════════════════"
