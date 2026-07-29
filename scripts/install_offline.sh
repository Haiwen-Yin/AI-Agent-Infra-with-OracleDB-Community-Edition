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
# Validate the platform-specific wheel set before pip changes the environment.
# Pip will select the compatible wheel when multiple platform builds of the
# same package/version are present in vendor/.
"$PYTHON_BIN" "$SCRIPT_DIR/verify_deps.py"
PIP_REQ_FILE="$REQ_FILE"
TEMP_REQ_FILE=""
if [[ -d "$VENDOR_DIR/yaspy" ]]; then
    # yaspy is shipped as a native extension, not as a pip distribution.
    TEMP_REQ_FILE="$(mktemp)"
    sed -E '/^[[:space:]]*yaspy([<=>]|$)/d' "$REQ_FILE" >"$TEMP_REQ_FILE"
    PIP_REQ_FILE="$TEMP_REQ_FILE"
    trap 'rm -f "$TEMP_REQ_FILE"' EXIT
fi
"$PYTHON_BIN" -m pip install --no-index --find-links "$VENDOR_DIR" -r "$PIP_REQ_FILE"
echo "[install] Done. Verifying installed dependency set..."
"$PYTHON_BIN" "$SCRIPT_DIR/verify_deps.py"
