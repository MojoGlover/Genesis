#!/bin/bash
# start.sh — Start a BlackZero agent
# Usage: ./start.sh [agent_id]
# Default: blackzero

set -e

AGENT_ID="${1:-blackzero}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find mission file
MISSION_FILE=""
if [ -f "$SCRIPT_DIR/missions/${AGENT_ID^^}.mission.txt" ]; then
    MISSION_FILE="$SCRIPT_DIR/missions/${AGENT_ID^^}.mission.txt"
elif [ -f "/Users/darnieglover/ai/cmptrblk/GENESIS/missions/${AGENT_ID^^}.mission.txt" ]; then
    MISSION_FILE="/Users/darnieglover/ai/cmptrblk/GENESIS/missions/${AGENT_ID^^}.mission.txt"
fi

if [ -z "$MISSION_FILE" ]; then
    echo "ERROR: No mission file found for '${AGENT_ID^^}'"
    echo "Create one at: $SCRIPT_DIR/missions/${AGENT_ID^^}.mission.txt"
    exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Starting: $AGENT_ID"
echo "  Mission:  $MISSION_FILE"
echo "  PlugOps:  ${PLUGOPS_URL:-ws://localhost:9000/ws/$AGENT_ID}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$SCRIPT_DIR"

AGENT_ID="$AGENT_ID" \
PLUGOPS_URL="${PLUGOPS_URL:-ws://localhost:9000/ws/$AGENT_ID}" \
PYTHONUNBUFFERED=1 \
python3 main_agent.py
