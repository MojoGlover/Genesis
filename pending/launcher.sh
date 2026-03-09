#!/bin/bash
# Engineer0 Launcher - Starts all services and opens dashboard

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DASHBOARD_PORT=8050
DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}"
PROJECT_DIR="$HOME/ai/GENESIS"
VENV_DIR="$PROJECT_DIR/venv"
LOG_DIR="$PROJECT_DIR/logs"

# Create logs directory
mkdir -p "$LOG_DIR"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                                                          ║${NC}"
echo -e "${BLUE}║         🤖 Engineer0 - Autonomous AI Agent 🤖           ║${NC}"
echo -e "${BLUE}║                                                          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to check if a port is in use
check_port() {
    lsof -i ":$1" > /dev/null 2>&1
}

# Function to kill process on port
kill_port() {
    local port=$1
    echo -e "${YELLOW}Stopping existing process on port $port...${NC}"
    lsof -ti ":$port" | xargs kill -9 2>/dev/null || true
    sleep 1
}

# Function to check if virtual environment exists
check_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
        python3 -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip
        pip install -e "$PROJECT_DIR"
        echo -e "${GREEN}✓ Virtual environment created${NC}"
    else
        echo -e "${GREEN}✓ Virtual environment found${NC}"
    fi
}

# Function to activate virtual environment
activate_venv() {
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✓ Virtual environment activated${NC}"
}

# Function to check Ollama
check_ollama() {
    echo -e "${BLUE}Checking Ollama...${NC}"
    if ! command -v ollama &> /dev/null; then
        echo -e "${RED}✗ Ollama not installed${NC}"
        echo -e "${YELLOW}Please install Ollama: https://ollama.ai${NC}"
        exit 1
    fi
    
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${YELLOW}Starting Ollama...${NC}"
        nohup ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
        sleep 3
    fi
    
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Ollama is running${NC}"
    else
        echo -e "${RED}✗ Failed to start Ollama${NC}"
        exit 1
    fi
}

# Function to start dashboard
start_dashboard() {
    echo -e "${BLUE}Starting Engineer0 Dashboard...${NC}"
    
    if check_port $DASHBOARD_PORT; then
        kill_port $DASHBOARD_PORT
    fi
    
    cd "$PROJECT_DIR"
    
    nohup python3 -m core.monitoring.dashboard_v2 > "$LOG_DIR/dashboard.log" 2>&1 &
    DASHBOARD_PID=$!
    
    echo $DASHBOARD_PID > "$LOG_DIR/dashboard.pid"
    
    echo -e "${YELLOW}Waiting for dashboard to start...${NC}"
    for i in {1..30}; do
        if check_port $DASHBOARD_PORT; then
            echo -e "${GREEN}✓ Dashboard started (PID: $DASHBOARD_PID)${NC}"
            return 0
        fi
        sleep 1
    done
    
    echo -e "${RED}✗ Dashboard failed to start${NC}"
    cat "$LOG_DIR/dashboard.log"
    exit 1
}

# Function to open browser
open_browser() {
    echo -e "${BLUE}Opening dashboard in browser...${NC}"
    sleep 2
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        open "$DASHBOARD_URL"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v xdg-open &> /dev/null; then
            xdg-open "$DASHBOARD_URL"
        elif command -v gnome-open &> /dev/null; then
            gnome-open "$DASHBOARD_URL"
        fi
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        start "$DASHBOARD_URL"
    fi
    
    echo -e "${GREEN}✓ Browser opened${NC}"
}

# Function to show status
show_status() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                  🚀 Engineer0 is running! 🚀             ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BLUE}Dashboard URL:${NC}    $DASHBOARD_URL"
    echo -e "  ${BLUE}Dashboard PID:${NC}    $(cat $LOG_DIR/dashboard.pid 2>/dev/null || echo 'N/A')"
    echo -e "  ${BLUE}Logs:${NC}             $LOG_DIR"
    echo ""
    echo -e "${YELLOW}Commands:${NC}"
    echo -e "  Stop:     ./launcher.sh stop"
    echo -e "  Restart:  ./launcher.sh restart"
    echo -e "  Logs:     tail -f $LOG_DIR/dashboard.log"
    echo ""
}

# Function to stop all services
stop_services() {
    echo ""
    echo -e "${YELLOW}Stopping Engineer0 services...${NC}"
    
    if [ -f "$LOG_DIR/dashboard.pid" ]; then
        DASH_PID=$(cat "$LOG_DIR/dashboard.pid")
        if ps -p $DASH_PID > /dev/null 2>&1; then
            kill $DASH_PID 2>/dev/null || true
            echo -e "${GREEN}✓ Dashboard stopped${NC}"
        fi
        rm "$LOG_DIR/dashboard.pid"
    fi
    
    if check_port $DASHBOARD_PORT; then
        kill_port $DASHBOARD_PORT
    fi
    
    echo -e "${GREEN}✓ All services stopped${NC}"
}

# Trap Ctrl+C
trap 'stop_services; exit 0' INT TERM

# Main execution
case "${1:-start}" in
    start)
        check_venv
        activate_venv
        check_ollama
        start_dashboard
        open_browser
        show_status
        wait
        ;;
    
    stop)
        stop_services
        ;;
    
    restart)
        stop_services
        sleep 2
        exec "$0" start
        ;;
    
    status)
        if check_port $DASHBOARD_PORT; then
            echo -e "${GREEN}✓ Engineer0 is running${NC}"
            echo -e "  Dashboard: $DASHBOARD_URL"
        else
            echo -e "${RED}✗ Engineer0 is not running${NC}"
        fi
        ;;
    
    logs)
        tail -f "$LOG_DIR/dashboard.log"
        ;;
    
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
