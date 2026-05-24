#!/bin/bash
# ============================================================================
# Oracle Memory System v2.3.0 - Web Server Control Script
# Usage: ./start_web_server.sh {start|stop|restart|status|config}
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_FILE="$SCRIPT_DIR/scripts/visualization/server.py"
CONFIG_FILE="$SCRIPT_DIR/config.json"
PID_FILE="/tmp/oracle_memory_viz.pid"
LOG_FILE="$SCRIPT_DIR/viz_server.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

_detect_python() {
    local candidates=(
        "/home/linuxbrew/.linuxbrew/bin/python3.14"
        "/home/linuxbrew/.linuxbrew/bin/python3.13"
        "/home/linuxbrew/.linuxbrew/bin/python3.12"
        "/home/linuxbrew/.linuxbrew/bin/python3"
    )
    for p in "${candidates[@]}"; do
        if [ -x "$p" ]; then
            echo "$p"
            return 0
        fi
    done
    if command -v python3 &>/dev/null; then
        local ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")
        if [ "$ver" != "0" ] && [ "$(printf '%s\n' "3.8" "$ver" | sort -V | head -1)" = "3.8" ]; then
            echo "python3"
            return 0
        fi
    fi
    return 1
}

_read_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "{}"; return
    fi
    cat "$CONFIG_FILE"
}

_config_val() {
    local section="$1" key="$2" default="$3"
    if [ -f "$CONFIG_FILE" ] && command -v /home/linuxbrew/.linuxbrew/bin/python3.14 &>/dev/null; then
        local val=$(/home/linuxbrew/.linuxbrew/bin/python3.14 -c "
import json
c=json.load(open('$CONFIG_FILE'))
v=c.get('$section',{}).get('$key','$default')
print(v)
" 2>/dev/null)
        [ -n "$val" ] && { echo "$val"; return; }
    fi
    echo "$default"
}

load_env() {
    CFG_DB_USER="${MEMORY_DB_USER:-$(_config_val database user openclaw)}"
    CFG_DB_PASS="${MEMORY_DB_PASSWORD:-$(_config_val database password hermes)}"
    CFG_DB_DSN="${MEMORY_DB_DSN:-$(_config_val database dsn '10.10.10.130:1521/openclaw')}"
    CFG_HOST="${MEMORY_SERVER_HOST:-$(_config_val server host 0.0.0.0)}"
    CFG_PORT="${MEMORY_SERVER_PORT:-$(_config_val server port 8000)}"
    CFG_TIMEOUT="${MEMORY_SESSION_TIMEOUT:-$(_config_val server session_timeout 300)}"
    CFG_POOL_MIN="$(_config_val database pool_min 2)"
    CFG_POOL_MAX="$(_config_val database pool_max 5)"
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    pgrep -f "scripts/visualization/server.py" 2>/dev/null | head -1
}

is_running() {
    local pid=$(get_pid)
    [ -n "$pid" ]
}

do_status() {
    load_env
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  Oracle Memory System v2.3.0${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    if is_running; then
        local pid=$(get_pid)
        echo -e "  Status:  ${GREEN}RUNNING${NC} (PID: $pid)"
        local uptime_ps=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
        [ -n "$uptime_ps" ] && echo -e "  Uptime:  ${GREEN}$uptime_ps${NC}"
    else
        echo -e "  Status:  ${RED}STOPPED${NC}"
    fi
    echo ""
    echo -e "  Host:    ${CFG_HOST:-0.0.0.0}"
    echo -e "  Port:    ${CFG_PORT:-8000}"
    echo -e "  Timeout: ${CFG_TIMEOUT:-300}s"
    echo -e "  DSN:     ${CFG_DB_DSN:-not set}"
    echo -e "  Python:  ${PYTHON:-not detected}"
    echo -e "  Log:     $LOG_FILE"
    echo -e "  PID:     $PID_FILE"
    echo ""
}

do_start() {
    load_env
    if is_running; then
        echo -e "${YELLOW}Server already running (PID: $(get_pid))${NC}"
        echo -e "Use '${0##*/} restart' to restart or '${0##*/} status' for info."
        exit 0
    fi

    PYTHON=$(_detect_python)
    if [ -z "$PYTHON" ]; then
        echo -e "${RED}Error: No suitable Python 3.8+ found${NC}"
        echo -e "${YELLOW}Install oracledb-compatible Python (3.8+) and update script${NC}"
        exit 1
    fi

    if ! $PYTHON -c "import oracledb" 2>/dev/null; then
        echo -e "${YELLOW}oracledb not installed for $PYTHON, installing...${NC}"
        $PYTHON -m pip install oracledb -q 2>/dev/null || {
            echo -e "${RED}Failed to install oracledb${NC}"; exit 1
        }
    fi

    if [ ! -f "$SERVER_FILE" ]; then
        echo -e "${RED}Error: Server file not found: $SERVER_FILE${NC}"
        exit 1
    fi

    if ss -tlnp 2>/dev/null | grep -q ":${CFG_PORT} "; then
        echo -e "${YELLOW}Port $CFG_PORT is in use, freeing...${NC}"
        pkill -f "scripts/visualization/server.py" 2>/dev/null || true
        sleep 2
    fi

    export MEMORY_DB_USER="$CFG_DB_USER"
    export MEMORY_DB_PASSWORD="$CFG_DB_PASS"
    export MEMORY_DB_DSN="$CFG_DB_DSN"
    export MEMORY_SERVER_HOST="$CFG_HOST"
    export MEMORY_SERVER_PORT="$CFG_PORT"
    export MEMORY_SESSION_TIMEOUT="$CFG_TIMEOUT"

    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  Starting Oracle Memory Web Server${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo -e "  Python:  $PYTHON"
    echo -e "  Host:    ${GREEN}$CFG_HOST${NC}"
    echo -e "  Port:    ${GREEN}$CFG_PORT${NC}"
    echo -e "  DSN:     $CFG_DB_DSN"
    echo -e "  Log:     $LOG_FILE"
    echo ""

    nohup $PYTHON -u "$SERVER_FILE" >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    for i in $(seq 1 45); do
        sleep 1
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "${RED}Server process exited unexpectedly${NC}"
            echo -e "${YELLOW}Last log lines:${NC}"
            tail -20 "$LOG_FILE" 2>/dev/null
            rm -f "$PID_FILE"
            exit 1
        fi
        if ss -tlnp 2>/dev/null | grep -qE ":${CFG_PORT}\b"; then
            local ip=$(hostname -I 2>/dev/null | awk '{print $1}')
            echo -e "${GREEN}Server started successfully! (PID: $pid)${NC}"
            echo ""
            echo -e "  URLs:"
            echo -e "    Local:    ${GREEN}http://localhost:$CFG_PORT${NC}"
            [ -n "$ip" ] && echo -e "    Network:  ${GREEN}http://$ip:$CFG_PORT${NC}"
            echo ""
            echo -e "  Pages:"
            echo -e "    Knowledge:  /knowledge"
            echo -e "    Memory:     /memory"
            echo -e "    Agents:     /agents"
            echo -e "    Tasks:      /tasks"
            echo ""
            echo -e "  Login: ${YELLOW}admin / admin123${NC}"
            echo ""
            echo -e "  Commands: ${0##*/} {start|stop|restart|status|config}"
            return 0
        fi
    done

    echo -e "${YELLOW}Server process alive but port not listening after 30s${NC}"
    echo -e "${YELLOW}Check log: tail -f $LOG_FILE${NC}"
    exit 1
}

do_stop() {
    if ! is_running; then
        echo -e "${YELLOW}Server not running${NC}"
        rm -f "$PID_FILE"
        return 0
    fi
    local pid=$(get_pid)
    echo -e "${YELLOW}Stopping server (PID: $pid)...${NC}"
    kill "$pid" 2>/dev/null || true

    for i in $(seq 1 10); do
        sleep 1
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "${GREEN}Server stopped${NC}"
            rm -f "$PID_FILE"
            return 0
        fi
    done

    echo -e "${YELLOW}Force killing...${NC}"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
    rm -f "$PID_FILE"
    echo -e "${GREEN}Server killed${NC}"
}

do_restart() {
    do_stop
    sleep 1
    do_start
}

do_config() {
    load_env
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  Configuration${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo -e "  Config file: ${CFG_CONFIG:-$CONFIG_FILE}"
    [ ! -f "$CONFIG_FILE" ] && echo -e "  ${YELLOW}(file not found, using defaults)${NC}"
    echo ""
    echo -e "  ${BLUE}[database]${NC}"
    echo -e "    user:          $CFG_DB_USER"
    echo -e "    password:      ****"
    echo -e "    dsn:           $CFG_DB_DSN"
    echo -e "    pool_min:      $CFG_POOL_MIN"
    echo -e "    pool_max:      $CFG_POOL_MAX"
    echo ""
    echo -e "  ${BLUE}[server]${NC}"
    echo -e "    host:           $CFG_HOST"
    echo -e "    port:           $CFG_PORT"
    echo -e "    session_timeout: $CFG_TIMEOUT"
    echo ""
    echo -e "  ${BLUE}[environment overrides]${NC}"
    echo -e "    MEMORY_DB_USER           -> DB user"
    echo -e "    MEMORY_DB_PASSWORD       -> DB password"
    echo -e "    MEMORY_DB_DSN            -> DB DSN"
    echo -e "    MEMORY_SERVER_HOST       -> Server host"
    echo -e "    MEMORY_SERVER_PORT       -> Server port"
    echo -e "    MEMORY_SESSION_TIMEOUT   -> Session timeout (seconds)"
    echo ""
    echo -e "  ${BLUE}[paths]${NC}"
    echo -e "    Python:    $PYTHON"
    echo -e "    Server:    $SERVER_FILE"
    echo -e "    PID file:  $PID_FILE"
    echo -e "    Log file:  $LOG_FILE"
    echo ""

    if [ -f "$CONFIG_FILE" ]; then
        echo -e "  ${BLUE}[raw config.json]${NC}"
        cat "$CONFIG_FILE"
        echo ""
    fi
}

do_log() {
    if [ -f "$LOG_FILE" ]; then
        tail -50 "$LOG_FILE"
    else
        echo -e "${YELLOW}No log file at $LOG_FILE${NC}"
    fi
}

PYTHON=$(_detect_python || echo "")
load_env

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    status)  do_status ;;
    config)  do_config ;;
    log)     do_log ;;
    *)
        echo "Oracle Memory System v2.3.0 - Web Server Control"
        echo ""
        echo "Usage: ${0##*/} {start|stop|restart|status|config|log}"
        echo ""
        echo "Commands:"
        echo "  start    Start the web server (daemon mode)"
        echo "  stop     Stop the web server"
        echo "  restart  Restart the web server"
        echo "  status   Show server status and configuration"
        echo "  config   Display full configuration details"
        echo "  log      Show last 50 lines of server log"
        echo ""
        echo "Configuration: Edit config.json or set environment variables:"
        echo "  MEMORY_DB_USER, MEMORY_DB_PASSWORD, MEMORY_DB_DSN"
        echo "  MEMORY_SERVER_HOST, MEMORY_SERVER_PORT, MEMORY_SESSION_TIMEOUT"
        exit 1
        ;;
esac
