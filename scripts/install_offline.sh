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
pip install --no-index --find-links "$VENDOR_DIR" -r "$REQ_FILE"
echo "[install] Done. Verifying..."
python3.14 "$SCRIPT_DIR/verify_deps.py"
