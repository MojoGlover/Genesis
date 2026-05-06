#!/usr/bin/env bash
cd "$(dirname "$0")"
for name in test_math_a test_math_b node; do
  if [[ -f run/$name.pid ]]; then
    pid=$(cat run/$name.pid)
    kill "$pid" 2>/dev/null && echo "[stop] $name pid=$pid killed" || echo "[stop] $name pid=$pid not running"
    rm -f run/$name.pid
  fi
done
