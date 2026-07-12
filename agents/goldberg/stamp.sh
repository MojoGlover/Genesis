#!/bin/bash
# stamp.sh — Create a clean new agent from BlackZero
# Usage: ./stamp.sh <agent_id> "<agent_name>" "<role>" <ollama_model>
# Example: ./stamp.sh engineer0 "Engineer0" "Systems, code & infrastructure" engineer0:latest

set -e

AGENT_ID="$1"
AGENT_NAME="$2"
AGENT_ROLE="$3"
AGENT_MODEL="$4"

if [ -z "$AGENT_ID" ] || [ -z "$AGENT_NAME" ] || [ -z "$AGENT_ROLE" ] || [ -z "$AGENT_MODEL" ]; then
    echo "Usage: ./stamp.sh <agent_id> <agent_name> <role> <model>"
    echo "Example: ./stamp.sh engineer0 \"Engineer0\" \"Systems & infrastructure\" engineer0:latest"
    exit 1
fi

BLACKZERO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLEAN_NAME=$(echo "$AGENT_NAME" | tr -d ' ')
TARGET_DIR="/Users/darnieglover/ai/cmptrblk/$CLEAN_NAME"
DATA_DIR="$HOME/.${AGENT_ID}"
AGENT_ID_UPPER=$(echo "$AGENT_ID" | tr '[:lower:]' '[:upper:]')
MISSION_FILE="/Users/darnieglover/ai/cmptrblk/GENESIS/missions/${AGENT_ID_UPPER}.mission.txt"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Stamping: $AGENT_NAME"
echo "  Target:   $TARGET_DIR"
echo "  Model:    $AGENT_MODEL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -d "$TARGET_DIR" ]; then
    echo "ERROR: $TARGET_DIR already exists. Remove it first if you want to re-stamp."
    exit 1
fi

# 1. Copy code only — no memory, no test artifacts, no runtime data
mkdir -p "$TARGET_DIR"
cp -r "$BLACKZERO_DIR/agent"        "$TARGET_DIR/"
cp    "$BLACKZERO_DIR/main_agent.py" "$TARGET_DIR/"
cp    "$BLACKZERO_DIR/start.sh"      "$TARGET_DIR/"
cp    "$BLACKZERO_DIR/test_agent.py" "$TARGET_DIR/"
cp    "$BLACKZERO_DIR/requirements.txt" "$TARGET_DIR/"

# 2. Create config.yaml with filled-in values (from template, not live config)
sed \
    -e "s|{AGENT_NAME}|$AGENT_NAME|g" \
    -e "s|{AGENT_ALIAS}|$AGENT_ID|g" \
    -e "s|{AGENT_ROLE}|$AGENT_ROLE|g" \
    -e "s|{agent_slug}|$AGENT_ID|g" \
    -e "s|{AGENT_MODEL}|$AGENT_MODEL|g" \
    "$BLACKZERO_DIR/config.template.yaml" > "$TARGET_DIR/config.yaml"

# 3. Create clean data directory
mkdir -p "$DATA_DIR"

# 4. Check mission
if [ ! -f "$MISSION_FILE" ]; then
    echo ""
    echo "⚠️  WARNING: No mission file found at:"
    echo "   $MISSION_FILE"
    echo "   Create it before starting $AGENT_NAME."
    echo "   The agent will refuse to start without a mission."
fi

echo ""
echo "✅ $AGENT_NAME stamped to $TARGET_DIR"
echo ""
echo "Next steps:"
if [ ! -f "$MISSION_FILE" ]; then
echo "  1. Create mission: $MISSION_FILE"
echo "  2. Start agent:    cd $TARGET_DIR && ./start.sh $AGENT_ID"
else
echo "  1. Start agent:    cd $TARGET_DIR && ./start.sh $AGENT_ID"
fi
