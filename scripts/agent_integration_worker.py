"""Bounded integration delivery and reconciliation worker; no autonomous tasks."""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import registered_protocols, telemetry_delivery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        registered_protocols.reconcile_calls()
        telemetry_delivery.reconcile()
        result = telemetry_delivery.deliver_one()
        print(result, flush=True)
        if args.once:
            return
        if result["status"] == "IDLE":
            time.sleep(2)


if __name__ == "__main__":
    main()
