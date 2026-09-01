#!/usr/bin/env bash
# Retired in v4.4.11: releases require RHEL 9.8+ (Oracle Linux 9.8+, glibc 2.34+).
set -euo pipefail
echo "[ERROR] The RHEL 8/manylinux_2_28 cryptography build is retired." >&2
echo "[ERROR] Use the pinned manylinux_2_34 wheel shipped in vendor/." >&2
exit 1
