"""Bounded built-in knowledge index worker.

The worker performs one database-authoritative reindex pass and can be run by
systemd. It never publishes, withdraws, or changes access policies.
"""
from __future__ import annotations
import argparse
import json
import os
import time
from datetime import datetime, timezone

from lib import builtin_knowledge


def run_once(actor: str, limit: int) -> dict:
    result = builtin_knowledge.reindex_packages(actor, limit)
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "actor": actor, **result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", default=os.environ.get("CX_INDEX_ACTOR", "SYSTEM_INDEXER"))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--interval", type=int, default=0, help="seconds; zero runs once")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()
    if not args.actor.strip() or not 1 <= args.limit <= 100 or args.interval < 0:
        parser.error("actor, limit, or interval is invalid")
    while True:
        try:
            result = run_once(args.actor.strip(), args.limit)
            payload = json.dumps(result, ensure_ascii=False)
            print(payload, flush=True)
            if args.output:
                with open(args.output, "a", encoding="utf-8") as stream:
                    stream.write(payload + "\n")
        except Exception as exc:
            print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), flush=True)
            return 1
        if not args.interval:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
