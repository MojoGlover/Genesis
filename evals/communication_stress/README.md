# Communication Stress Test

Stress harness for `modules/communication/`. Two test agents (TestMath_A,
TestMath_B) exchange simple math problems through the node for thousands (or
millions) of iterations, logging every exchange with latency.

Per GENESIS Rule 21, the Communication Module does not graduate to Botico
until this harness runs cleanly at scale.

## Run

```bash
./run_stress.sh            # 10,000 iterations (smoke)
./run_stress.sh 100000     # 100k iterations
./run_stress.sh 10000000   # overnight stress
tail -f logs/test_math_a.log
./stop.sh
```

## Success criteria (Rule 22 — Validation)

A run is a pass only if the final summary shows:

```
counters={'sent': N, 'correct': N, 'wrong': 0, 'timeout': 0, 'errors': 0}
```

Any non-zero `wrong`, `timeout`, or `errors` → investigate before graduating.

Latency stats (`p50`, `p95`, `p99`, `max`) are recorded for regression tracking.

## Files

- `test_math_a.py` — asker agent
- `test_math_b.py` — solver agent
- `run_stress.sh` — starts node + both agents
- `stop.sh` — kills all three
- `logs/` — per-process stdout/stderr
- `run/` — PID files
