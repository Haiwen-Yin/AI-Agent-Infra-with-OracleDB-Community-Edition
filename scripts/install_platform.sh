#!/usr/bin/env bash
# Chuanxu Bootstrap Deployment Agent wrapper.  The Python command owns all
# database actions; this shell wrapper never constructs SQL or prints secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/python_runtime.sh"
VENV_PYTHON="${CX_VENV_DIR:-$ROOT_DIR/.venv}/bin/python"
if [[ -z "${PYTHON_BIN:-}" && -x "$VENV_PYTHON" ]]; then
  PYTHON_BIN="$VENV_PYTHON"
elif ! PYTHON_BIN="$(cx_resolve_python "${PYTHON_BIN:-}")"; then
  echo "Python 3.14+ is required; set PYTHON_BIN to an accessible interpreter." >&2
  exit 1
fi
cx_prepare_python_environment "$PYTHON_BIN"
exec "$PYTHON_BIN" "$SCRIPT_DIR/bootstrap_deployment_agent.py" "$@"
