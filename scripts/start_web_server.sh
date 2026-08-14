#!/usr/bin/env bash
# Chuanxu v4.4.4 - AI Agent Infra v4.4.4 - {{EDITION_LABEL}} unified FastAPI/Uvicorn server controller.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_HELPER="$SCRIPT_DIR/scripts/python_runtime.sh"
if [[ ! -f "$RUNTIME_HELPER" ]]; then
  echo "Python runtime helper is missing: $RUNTIME_HELPER" >&2
  exit 1
fi
source "$RUNTIME_HELPER"
VENV_PYTHON="${CX_VENV_DIR:-$SCRIPT_DIR/.venv}/bin/python"
if [[ -z "${PYTHON_BIN:-}" && -x "$VENV_PYTHON" ]]; then
  PYTHON="$VENV_PYTHON"
elif ! PYTHON="$(cx_resolve_python "${PYTHON_BIN:-}")"; then
  echo "Python 3.14+ is required; set PYTHON_BIN to an accessible interpreter." >&2
  exit 1
fi
cx_prepare_python_environment "$PYTHON"
YASHAN_CLIENT_LIB="${CX_YASHAN_LIB_DIR:-$SCRIPT_DIR/.runtime/yashandb-client/lib}"
if [[ -d "$YASHAN_CLIENT_LIB" ]]; then
  export LD_LIBRARY_PATH="$YASHAN_CLIENT_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

DB_DIALECT="{{DATABASE_DIALECT}}"
PROFILE="${CX_RUNTIME_PROFILE:-production}"
HOST="${MEMORY_SERVER_HOST:-0.0.0.0}"
PORT="${MEMORY_SERVER_PORT:-8000}"
PID_FILE="${CX_WEB_PID_FILE:-/tmp/chuanxu-${DB_DIALECT}.pid}"
LOG_FILE="${CX_WEB_LOG_FILE:-$SCRIPT_DIR/chuanxu_web.log}"

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR/scripts:$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export CX_DATABASE_DIALECT="$DB_DIALECT"
export CX_RUNTIME_PROFILE="$PROFILE"
export AI_AGENT_RELEASE_DATE="2026-08-14"

read_config() {
  "$PYTHON" - "$1" "$2" <<'PY'
import sys
try:
    from lib.config import get_config
    cfg = get_config()
    section, key = sys.argv[1:3]
    value = getattr(getattr(cfg, section), key, "")
    print(value if value is not None else "")
except Exception:
    print("")
PY
}

if [[ -z "${MEMORY_SERVER_HOST:-}" ]]; then
  HOST="$(read_config server host || true)"
  HOST="${HOST:-0.0.0.0}"
fi
if [[ -z "${MEMORY_SERVER_PORT:-}" ]]; then
  PORT="$(read_config server port || true)"
  PORT="${PORT:-8000}"
fi
export MEMORY_SERVER_HOST="$HOST"
export MEMORY_SERVER_PORT="$PORT"

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(<"$PID_FILE")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

stop_server() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "Chuanxu is stopped."
    return 0
  fi
  local pid
  pid="$(<"$PID_FILE")"
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "Chuanxu stopped."
      return 0
    fi
    sleep 0.25
  done
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "Chuanxu stopped after forced termination."
}

start_server() {
  if is_running; then
    echo "Chuanxu is already running (PID $(<"$PID_FILE"))."
    return 0
  fi
  if [[ -x "$SCRIPT_DIR/scripts/config_wizard.sh" && ! -f "$SCRIPT_DIR/config.json" && -z "${CX_CONFIG_PATH:-}" ]]; then
    "$SCRIPT_DIR/scripts/config_wizard.sh"
  fi
  if [[ -f "$SCRIPT_DIR/scripts/verify_deps.py" ]] && ! "$PYTHON" "$SCRIPT_DIR/scripts/verify_deps.py"; then
    echo "Offline dependency verification failed; resolve the reported vendor/ and platform errors before starting." >&2
    exit 1
  fi
  if ! "$PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
    echo "FastAPI and Uvicorn are not installed for the selected Python. Run scripts/install_offline.sh with the same Python 3.14+ interpreter, then retry." >&2
    exit 1
  fi
  echo "Starting Chuanxu v4.4.4 ($DB_DIALECT, $PROFILE) on $HOST:$PORT"
  setsid nohup "$PYTHON" -m uvicorn web_app:app --host "$HOST" --port "$PORT" \
    --proxy-headers --no-access-log >>"$LOG_FILE" 2>&1 &
  echo "$!" >"$PID_FILE"
  for _ in {1..40}; do
    if is_running; then
      if "$PYTHON" - "$HOST" "$PORT" <<'PY' >/dev/null 2>&1
import sys, urllib.request
host, port = sys.argv[1:]
urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
PY
      then
        echo "Chuanxu started (PID $(<"$PID_FILE"))."
        return 0
      fi
    fi
    sleep 0.5
  done
  echo "Chuanxu failed to start; see $LOG_FILE." >&2
  stop_server || true
  exit 1
}

case "${1:-status}" in
  start) start_server ;;
  stop) stop_server ;;
  restart) stop_server; start_server ;;
  status)
    if is_running; then
      echo "Chuanxu is running (PID $(<"$PID_FILE"), $DB_DIALECT, $PROFILE, $HOST:$PORT)."
    else
      echo "Chuanxu is stopped ($DB_DIALECT, $HOST:$PORT)."
      exit 1
    fi
    ;;
  config)
    echo "database=$DB_DIALECT"
    echo "profile=$PROFILE"
    echo "host=$HOST"
    echo "port=$PORT"
    echo "python=$PYTHON"
    echo "pid=$PID_FILE"
    echo "log=$LOG_FILE"
    ;;
  log) tail -50 "$LOG_FILE" 2>/dev/null || true ;;
  *) echo "Usage: $0 {start|stop|restart|status|config|log}" >&2; exit 2 ;;
esac
