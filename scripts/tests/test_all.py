"""Oracle Memory System v2.0.0 - Master Test Runner"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.test_connection import run_all as run_connection
from tests.test_memory import run_all as run_memory
from tests.test_knowledge import run_all as run_knowledge
from tests.test_agent import run_all as run_agent
from tests.test_security import run_all as run_security


def main():
    print("=" * 60)
    print("Oracle Memory System v2.0.0 - Full Test Suite")
    print("=" * 60)

    suites = [
        ("Connection", run_connection),
        ("Memory", run_memory),
        ("Knowledge", run_knowledge),
        ("Agent", run_agent),
        ("Security", run_security),
    ]

    results = {}
    for name, runner in suites:
        print(f"\n--- {name} Tests ---")
        try:
            results[name] = runner()
        except Exception as e:
            print(f"ERROR: {name} suite crashed: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
