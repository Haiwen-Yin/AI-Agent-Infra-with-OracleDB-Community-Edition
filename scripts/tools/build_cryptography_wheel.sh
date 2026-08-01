#!/usr/bin/env bash
# Build the RHEL 8/glibc 2.28 compatibility wheel for cryptography 49.0.0.
# The source tree and build toolchain are deliberately supplied by the operator.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${CRYPTOGRAPHY_VERSION:-49.0.0}"
AUDITWHEEL_BIN="${AUDITWHEEL_BIN:-auditwheel}"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <cryptography-${VERSION}.tar.gz-or-source-dir> [output-dir]" >&2
  exit 2
fi

SOURCE="$1"
OUTPUT_DIR="${2:-$(pwd)/vendor}"

if [[ -f "$SCRIPT_DIR/../scripts/python_runtime.sh" ]]; then
  source "$SCRIPT_DIR/../scripts/python_runtime.sh"
elif [[ -f "$SCRIPT_DIR/../python_runtime.sh" ]]; then
  source "$SCRIPT_DIR/../python_runtime.sh"
else
  echo "[ERROR] Python runtime helper is missing." >&2
  exit 1
fi
PYTHON_BIN="$(cx_resolve_python "${PYTHON_BIN:-}")"
cx_prepare_python_environment "$PYTHON_BIN"

if [[ ! -e "$SOURCE" ]]; then
  echo "[ERROR] cryptography source was not found: $SOURCE" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python executable is not available: $PYTHON_BIN" >&2
  echo "        Set PYTHON_BIN to an accessible Python 3.14+ executable." >&2
  exit 1
fi
if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
  echo "[ERROR] $PYTHON_BIN has no usable pip module." >&2
  exit 1
fi
if ! command -v "$AUDITWHEEL_BIN" >/dev/null 2>&1; then
  echo "[ERROR] auditwheel is required to prove the glibc floor." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cryptography-${VERSION}.XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT

echo "[build] Python: $PYTHON_BIN"
echo "[build] Source: $SOURCE"
echo "[build] Target: manylinux_2_28_x86_64"
echo "[build] Building cryptography==$VERSION from source..."

# Keep the default build air-gapped. Set CARGO_NET_OFFLINE=false explicitly
# only when the approved build environment is allowed to fetch Rust crates.
export CARGO_NET_OFFLINE="${CARGO_NET_OFFLINE:-true}"

# --no-build-isolation keeps the build reproducible in an offline environment.
# Install the cryptography build requirements (Rust, maturin, cffi and the
# OpenSSL 3 development headers) in this interpreter before invoking the script.
"$PYTHON_BIN" -m pip wheel \
  --no-index \
  --no-deps \
  --no-binary=:all: \
  --no-build-isolation \
  --wheel-dir "$BUILD_DIR/raw" \
  "$SOURCE"

mapfile -t RAW_WHEELS < <(find "$BUILD_DIR/raw" -maxdepth 1 -type f -name "cryptography-${VERSION}-*.whl" -print)
if [[ "${#RAW_WHEELS[@]}" -ne 1 ]]; then
  echo "[ERROR] expected exactly one source-built cryptography wheel" >&2
  printf '  %s\n' "${RAW_WHEELS[@]}" >&2
  exit 1
fi

# auditwheel refuses to relabel binaries that reference newer GLIBC symbols.
# This makes a build accidentally performed on RHEL 9 fail closed instead of
# producing a wheel falsely advertised as usable on RHEL 8.
# Keep the upstream manylinux_2_34 wheel for newer customer systems. Only
# replace the locally built RHEL 8 artifact on repeatable builds.
rm -f "$OUTPUT_DIR"/cryptography-${VERSION}-*manylinux_2_28_x86_64.whl
"$AUDITWHEEL_BIN" repair \
  --plat manylinux_2_28_x86_64 \
  --wheel-dir "$OUTPUT_DIR" \
  "${RAW_WHEELS[0]}"

mapfile -t REPAIRED_WHEELS < <(find "$OUTPUT_DIR" -maxdepth 1 -type f -name "cryptography-${VERSION}-*manylinux_2_28_x86_64.whl" -print)
if [[ "${#REPAIRED_WHEELS[@]}" -ne 1 ]]; then
  echo "[ERROR] auditwheel did not produce one manylinux_2_28 wheel" >&2
  exit 1
fi

echo "[build] Produced: ${REPAIRED_WHEELS[0]}"
"$AUDITWHEEL_BIN" show "${REPAIRED_WHEELS[0]}"
echo "[build] Copy this wheel to shared/vendor/ before building the six editions."
