#!/bin/bash
# start.sh — Start a BlackZero agent
# Usage: ./start.sh [agent_id]
#
# Portability notes (do not "simplify" these away):
# - Uppercasing uses tr, not ${var^^} — macOS ships bash 3.2 which lacks it.
# - No absolute host paths — agents run on any plug (plugwan/plugfoe/RunPod).
# - PLUGOPS_URL is intentionally NOT defaulted here. main.py gives the env var
#   precedence over config.yaml, so defaulting it would silently override the
#   real PlugOps URL configured in config.yaml.

set -e

AGENT_ID="${1:-blackzero}"
AGENT_ID_UPPER="$(printf '%s' "$AGENT_ID" | tr '[:lower:]' '[:upper:]')"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

MISSION_FILE="$SCRIPT_DIR/missions/${AGENT_ID_UPPER}.mission.txt"
if [ ! -f "$MISSION_FILE" ]; then
    echo "ERROR: No mission file found for '${AGENT_ID_UPPER}'"
    echo "Create it at: $MISSION_FILE"
    exit 1
fi

echo "----------------------------------------"
echo "  Starting: $AGENT_ID"
echo "  Mission:  $MISSION_FILE"
echo "  PlugOps:  ${PLUGOPS_URL:-from config.yaml}"
echo "----------------------------------------"

cd "$SCRIPT_DIR"

AGENT_ID="$AGENT_ID" \
PYTHONUNBUFFERED=1 \
python3 main.py
