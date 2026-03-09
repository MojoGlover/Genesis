#!/bin/bash
# GENESIS Master Test Runner
# Runs tests for all modules

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

GENESIS_DIR="$HOME/ai/GENESIS"

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   GENESIS Module Test Runner         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

PASS=0
FAIL=0

test_module() {
    local module_dir="$1"
    local module_name="$2"
    
    local src="$GENESIS_DIR/$module_dir"
    
    if [ ! -d "$src" ]; then
        echo -e "${YELLOW}⚠️  $module_name: not found${NC}"
        return 0
    fi
    
    echo -e "${BLUE}Testing: $module_name${NC}"
    
    # Run quick import test
    cd "$src"
    if python3 -c "import sys; sys.path.insert(0, '.'); import ${module_dir}" 2>/dev/null; then
        echo -e "  ${GREEN}✓ Import OK${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗ Import FAILED${NC}"
        FAIL=$((FAIL + 1))
    fi
    
    # Run pytest if tests/ exists
    if [ -d "$src/tests" ]; then
        if python3 -m pytest "$src/tests" -q --tb=short 2>/dev/null; then
            echo -e "  ${GREEN}✓ Tests passed${NC}"
        else
            echo -e "  ${RED}✗ Tests failed${NC}"
            FAIL=$((FAIL + 1))
        fi
    else
        echo -e "  ${YELLOW}⚠️  No tests/ directory${NC}"
    fi
    echo ""
}

test_module "ai_starter" "AI Starter"
test_module "rasa_module" "Rasa Module"
test_module "vision_engine" "Vision Engine"
test_module "tablet_assistant" "Tablet Assistant"
test_module "scheduler" "Scheduler"

echo -e "Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✅ All modules OK!${NC}"
else
    echo -e "${RED}❌ Some modules need attention${NC}"
    exit 1
fi
