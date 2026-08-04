#!/bin/bash
# AI Agent Infra - Offline Dependency Installer
# Installs all Python packages from local vendor/ directory (no network required)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENDOR_DIR="$PROJECT_DIR/vendor"
REQ_FILE="$PROJECT_DIR/requirements.txt"

if [ ! -d "$VENDOR_DIR" ]; then
    echo "[ERROR] vendor/ directory not found at $VENDOR_DIR"
    echo "        Run this script from the project root directory."
    exit 1
fi

if [ ! -f "$REQ_FILE" ]; then
    echo "[ERROR] requirements.txt not found at $REQ_FILE"
    exit 1
fi

echo "[install] Installing dependencies from vendor/ (offline mode)..."
if [[ -f "$SCRIPT_DIR/python_runtime.sh" ]]; then
    # In a generated package this installer lives under scripts/.
    RUNTIME_HELPER="$SCRIPT_DIR/python_runtime.sh"
else
    # In the unified source tree it lives beside shared/scripts/.
    RUNTIME_HELPER="$SCRIPT_DIR/scripts/python_runtime.sh"
fi
if [[ ! -f "$RUNTIME_HELPER" ]]; then
    echo "[ERROR] Python runtime helper is missing: $RUNTIME_HELPER" >&2
    exit 1
fi
source "$RUNTIME_HELPER"
if ! PYTHON_BIN="$(cx_resolve_python "${PYTHON_BIN:-}")"; then
    echo "[ERROR] Python 3.14+ is required. Set PYTHON_BIN to an accessible interpreter." >&2
    exit 1
fi
cx_prepare_python_environment "$PYTHON_BIN"
if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    echo "[ERROR] $PYTHON_BIN has no pip module. Install pip for the same interpreter before retrying." >&2
    exit 1
fi
VENV_DIR="${CX_VENV_DIR:-$PROJECT_DIR/.venv}"
VENV_PYTHON="$VENV_DIR/bin/python"
# Homebrew and other PEP 668 Python installations deliberately reject global
# pip writes. A package-local virtual environment also keeps an offline
# deployment isolated from the operator's Python installation.
if [[ ! -x "$VENV_PYTHON" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
if ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 14) else 1)' >/dev/null 2>&1; then
    echo "[ERROR] package virtual environment does not use Python 3.14+" >&2
    exit 1
fi
# YashanDB ships a CPython-native driver rather than a wheel. Install it into
# the same package-local virtual environment before checking or starting the
# Web service; no user-site or global Python path is modified.
if [[ -d "$VENDOR_DIR/yaspy" ]]; then
    if [[ ! -f "$SCRIPT_DIR/install_yaspy.sh" ]]; then
        echo "[ERROR] YashanDB native-driver installer is missing." >&2
        exit 1
    fi
    CX_YASHAN_LIB_DIR="${CX_YASHAN_LIB_DIR:-$PROJECT_DIR/.runtime/yashandb-client/lib}" \
        PYTHON_BIN="$VENV_PYTHON" bash "$SCRIPT_DIR/install_yaspy.sh"
fi
# Validate the platform-specific wheel set before pip changes the environment.
# Pip will select the compatible wheel when multiple platform builds of the
# same package/version are present in vendor/.
"$VENV_PYTHON" "$SCRIPT_DIR/verify_deps.py"
PIP_REQ_FILE="$REQ_FILE"
TEMP_REQ_FILE=""
if [[ -d "$VENDOR_DIR/yaspy" ]]; then
    # yaspy is shipped as a native extension, not as a pip distribution.
    TEMP_REQ_FILE="$(mktemp)"
    sed -E '/^[[:space:]]*yaspy([<=>]|$)/d' "$REQ_FILE" >"$TEMP_REQ_FILE"
    PIP_REQ_FILE="$TEMP_REQ_FILE"
    trap 'rm -f "$TEMP_REQ_FILE"' EXIT
fi
"$VENV_PYTHON" -m pip install --no-index --find-links "$VENDOR_DIR" -r "$PIP_REQ_FILE"
echo "[install] Done. Verifying installed dependency set..."
"$VENV_PYTHON" "$SCRIPT_DIR/verify_deps.py"
