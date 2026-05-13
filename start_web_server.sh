#!/bin/bash
# ============================================================================
# Oracle Memory System - Quick Start Script
# Author: Haiwen (胖头鱼 🐟) | Version: v1.1.0
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_FILE="$SCRIPT_DIR/viz_server_local_js.py"
CONFIG_FILE="$SCRIPT_DIR/config.json"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Oracle Memory System Web Server${NC}"
echo -e "${BLUE}  Version: v1.1.0${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python3 not found${NC}"
    exit 1
fi

# Check oracledb
if ! python3 -c "import oracledb" 2>/dev/null; then
    echo -e "${YELLOW}Warning: oracledb not installed, installing...${NC}"
    pip3 install oracledb -q
fi

# Check server file
if [ ! -f "$SERVER_FILE" ]; then
    echo -e "${RED}Error: Server file not found: $SERVER_FILE${NC}"
    exit 1
fi

# Check config file
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${YELLOW}Warning: config.json not found, using defaults${NC}"
fi

# Display current configuration
echo -e "${BLUE}Configuration:${NC}"
if [ -f "$CONFIG_FILE" ]; then
    echo -e "  Config file: ${GREEN}$CONFIG_FILE${NC}"
fi
echo -e "  Host: ${GREEN}${MEMORY_SERVER_HOST:-0.0.0.0}${NC}"
echo -e "  Port: ${GREEN}${MEMORY_SERVER_PORT:-8000}${NC}"
echo -e "  Database: ${GREEN}${MEMORY_DB_DSN:-10.10.10.130:1521/openclaw}${NC}"
echo ""

# Check if port is in use
PORT=${MEMORY_SERVER_PORT:-8000}
if lsof -i :$PORT | grep -q LISTEN; then
    echo -e "${YELLOW}Warning: Port $PORT is already in use${NC}"
    echo -e "${YELLOW}Stopping existing process...${NC}"
    pkill -f "viz_server_local_js.py" || true
    sleep 2
fi

# Start server
echo -e "${GREEN}Starting server...${NC}"
cd "$SCRIPT_DIR"
python3 "$SERVER_FILE" &
SERVER_PID=$!

# Wait for server to start
sleep 3

# Check if server is running
if kill -0 $SERVER_PID 2>/dev/null; then
    echo ""
    echo -e "${GREEN}Server started successfully!${NC}"
    echo ""
    echo -e "${BLUE}Access URLs:${NC}"
    echo -e "  Local:   ${GREEN}http://localhost:$PORT${NC}"
    echo -e "  Network: ${GREEN}http://10.10.10.135:$PORT${NC}"
    echo ""
    echo -e "${BLUE}Default Credentials:${NC}"
    echo -e "  Username: ${YELLOW}admin${NC}"
    echo -e "  Password: ${YELLOW}admin123${NC}"
    echo ""
    echo -e "${BLUE}Features:${NC}"
    echo -e "  - Database authentication (PBKDF2)"
    echo -e "  - Knowledge graph visualization"
    echo -e "  - Memory content display"
    echo -e "  - Chinese/English toggle"
    echo -e "  - 5-minute session timeout"
    echo ""
    echo -e "${BLUE}Environment Variables:${NC}"
    echo -e "  MEMORY_DB_USER      - Database username"
    echo -e "  MEMORY_DB_PASSWORD  - Database password"
    echo -e "  MEMORY_DB_DSN       - Database DSN (host:port/service)"
    echo -e "  MEMORY_SERVER_PORT  - Server port (default: 8000)"
    echo -e "  MEMORY_SERVER_HOST  - Server host (default: 0.0.0.0)"
    echo -e "  MEMORY_SESSION_TIMEOUT - Session timeout in seconds"
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
    
    # Trap to cleanup
    trap "echo ''; echo -e '${RED}Stopping server...${NC}'; kill $SERVER_PID 2>/dev/null; exit 0" INT TERM
    
    # Wait for server process
    wait $SERVER_PID
else
    echo -e "${RED}Failed to start server${NC}"
    exit 1
fi
