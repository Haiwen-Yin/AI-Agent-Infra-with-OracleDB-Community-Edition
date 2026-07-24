"""AI Agent Infra v4.1.0 - Community Edition - Master Test Runner"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tests.test_connection import run_all as run_connection
from tests.test_memory import run_all as run_memory
from tests.test_knowledge import run_all as run_knowledge
from tests.test_agent import run_all as run_agent
from tests.test_graph import run_all as run_graph
from tests.test_harness import run_all as run_harness
from tests.test_security import run_all as run_security
from tests.test_workspace import run_all as run_workspace
from tests.test_spec import run_all as run_spec
from tests.test_collab import run_all as run_collab
from tests.test_credential import run_all as run_credential
from tests.test_embedding import run_all as run_embedding
from tests.test_unified_search import run_all as run_unified_search
from tests.test_search_api import run_all as run_search_api
from tests.test_skill import run_all as run_skill


def main():
    print("=" * 60)
    print("AI Agent Infra v4.1.0 - Community Edition - Full Test Suite")
    print("=" * 60)

    suites = [
        ("Connection", run_connection),
        ("Memory", run_memory),
        ("Knowledge", run_knowledge),
        ("Agent", run_agent),
        ("Graph", run_graph),
        ("Harness", run_harness),
        ("Security", run_security),
        ("Workspace", run_workspace),
        ("Spec", run_spec),
        ("Collab", run_collab),
        ("Credential", run_credential),
        ("Embedding", run_embedding),
        ("UnifiedSearch", run_unified_search),
        ("SearchAPI", run_search_api),
        ("Skill", run_skill),
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
