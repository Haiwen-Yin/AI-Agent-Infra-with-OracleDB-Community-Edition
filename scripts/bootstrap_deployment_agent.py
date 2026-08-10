#!/usr/bin/env python3.14
"""Package-local Bootstrap Deployment Agent command entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lib.deployment_orchestrator import DeploymentError, run


def main() -> int:
    parser = argparse.ArgumentParser(description="Chuanxu Bootstrap Deployment Agent")
    parser.add_argument("command", choices=("initialize", "upgrade", "resume", "status", "verify"))
    parser.add_argument("--database", choices=("oracle", "pg", "yashandb"), required=True)
    parser.add_argument("--edition", choices=("community", "enterprise"), required=True)
    parser.add_argument("--config", type=Path, default=SCRIPT_ROOT.parent / "config.json")
    parser.add_argument("--run-id", default="", help="required to resume a previous local deployment journal")
    args = parser.parse_args()
    try:
        result = run(args.command, database=args.database, edition=args.edition, config_path=args.config,
                     root=SCRIPT_ROOT.parent, run_id=args.run_id)
    except DeploymentError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0 if str(result.get("status") or "") not in {"FAILED", "FAILED_MANUAL_ACTION_REQUIRED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
