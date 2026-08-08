#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -z "${1:-}" ]; then
  echo "Usage: ./start.sh <signup-url>"
  exit 1
fi

pip3 install -q --upgrade playwright
python3 -m playwright install chromium

python3 concierge.py "$1"
