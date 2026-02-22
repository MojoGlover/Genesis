#!/bin/bash
# GENESIS Master Install Script

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

GENESIS_DIR="$HOME/ai/GENESIS"
ENGINEER0_VENV="$HOME/ai/Engineer0/venv"
PLUGOPS_VENV="$HOME/ai/PlugOps/venv"

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   GENESIS Module Installer           ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

MODULES="ai_starter rasa_module vision_engine tablet_assistant scheduler scraper"

install_into() {
    local venv="$1"
    local target_name="$2"
    
    if [ ! -d "$venv" ]; then
        echo -e "  ${YELLOW}⚠️  $target_name venv not found - skipping${NC}"
        return 0
    fi
    
    echo -e "${YELLOW}Installing into $target_name...${NC}"
    for module in $MODULES; do
        local src="$GENESIS_DIR/$module"
        if [ -d "$src" ]; then
            echo -e "  Installing ${BLUE}$module${NC}"
            "$venv/bin/pip" install -q -e "$src" 2>/dev/null && \
                echo -e "  ${GREEN}✓ $module${NC}" || \
                echo -e "  ${YELLOW}⚠️  $module (check deps)${NC}"
        fi
    done
    echo ""
}

install_into "$ENGINEER0_VENV" "Engineer0"
install_into "$PLUGOPS_VENV" "PlugOps"

echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   All modules installed! 🚀          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
