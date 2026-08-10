#!/usr/bin/env python3.14
"""Run one bounded, lease-protected managed Embedding worker batch."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lib.embedding_governance import run_managed_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Chuanxu managed Embedding worker")
    parser.add_argument("--worker-id", default=f"embedding-worker:{socket.gethostname()}")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run_managed_worker(args.worker_id, limit=max(1, min(args.limit, 100))), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
