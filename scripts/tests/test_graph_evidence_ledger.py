from pathlib import Path

import pytest

from tools.generate_graph_evidence_ledger import STATUSES, build_ledger, parse_tasks


def test_evidence_ledger_covers_every_open_spec_task():
    root = Path(__file__).resolve().parents[2]
    tasks_path = root / "openspec/changes/harden-graph-engineering-v4-3-3/tasks.md"
    if not tasks_path.is_file():
        pytest.skip("OpenSpec change ledger is intentionally retained only in the unified source tree")
    tasks = parse_tasks(tasks_path)
    ledger = build_ledger(tasks)
    assert len(ledger["entries"]) == len(tasks)
    assert {item["task_id"] for item in ledger["entries"]} == {item[0] for item in tasks}
    assert all(item["status"] in STATUSES and item["limitations"] and item["reviewer"] for item in ledger["entries"])


def test_evidence_ledger_never_promotes_deferred_work_to_proven():
    ledger = build_ledger([("7.4", "Streaming"), ("10.1", "Oracle migration")])
    assert ledger["entries"][0]["status"] == "DEFERRED"
    assert ledger["entries"][1]["status"] == "IMPLEMENTED_AND_PROVEN"
