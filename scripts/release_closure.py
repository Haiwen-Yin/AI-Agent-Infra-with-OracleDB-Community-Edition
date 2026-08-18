#!/usr/bin/env python3
"""Build the evidence-backed integrated v4.3.0 release gate.

The internal v4.2.1 Graph closure is consumed here as a milestone; it is not a
public release line or a separate archive.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "ai-agent-infra-release-closure/v2"
VERSION = "4.4.8"
PROFILE = "production"
DEPENDENCY_ORDER = [
    "contracts",
    "dependencies",
    "compiler",
    "executor",
    "runtime-state-events",
    "compatibility",
    "governance-evidence",
    "database-migrations",
    "browser",
    "failure-recovery",
    "capacity",
    "packages-docs",
]

GATES = (
        ("pure-contracts", "Portable Graph and identity contracts and security tests", "contracts"),
    ("dependencies", "Python 3.14 offline dependency closure and wheel integrity", "dependencies"),
    ("compiler", "Compiler structural, predicate, extension, and rejection tests", "compiler"),
    ("executor-compatibility", "Versioned Executor and legacy compatibility boundary", "executor"),
    ("runtime-events", "Durable Runtime, State, Inbox/Outbox, and Worker tests", "runtime-state-events"),
    ("governance-evidence", "Governance, evaluation, retention, hold, and evidence tests", "governance-evidence"),
    ("database-migrations", "Oracle, PostgreSQL/AGE, and YashanDB migration evidence", "database-migrations"),
    ("browser", "Current-release FastAPI browser and accessibility evidence", "browser"),
    ("failure-recovery", "Persistent transition failure and recovery matrix", "failure-recovery"),
    ("capacity", "5k/10k/50k/100k data and Worker capacity evidence", "capacity"),
        ("packages", "Six package, edition boundary, license, and purity checks", "packages-docs"),
        ("documentation", "Technical docs, Skill, API, and v4.3.0 maturity-boundary checks", "packages-docs"),
)


def _status(value: Any) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    normalized = str(value or "UNVERIFIED").upper()
    return normalized if normalized in {"PASS", "FAIL", "UNVERIFIED", "BLOCKED"} else "UNVERIFIED"


def _load_evidence(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(document, dict):
            continue
        gate_id = document.get("gate_id") or document.get("closure_gate")
        if gate_id:
            evidence_version = str(document.get("version", "")).strip()
            status = _status(document.get("status", document.get("passed")))
            if evidence_version and evidence_version != VERSION:
                # A previous release's PASS is useful history, never current
                # release evidence. Keep it visible but make the gate block.
                status = "BLOCKED"
            evidence[str(gate_id)] = {
                "status": status,
                "source": str(path),
                "evidence_version": evidence_version or None,
            }
    return evidence


def build_manifest(*, release_date: str, evidence: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    evidence = evidence or {}
    gates = []
    for gate_id, description, dependency in GATES:
        result = evidence.get(gate_id) or {}
        gates.append({
            "id": gate_id,
            "description": description,
            "dependency": dependency,
            "mandatory": True,
            "status": _status(result.get("status")),
            "source": result.get("source"),
        })
    releasable = all(item["status"] == "PASS" for item in gates)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "profile": PROFILE,
        "release_date": release_date,
        # The release has a production profile, while Graph Preview and other
        # capability-level previews remain explicitly gated at runtime.
        "experimental": True,
        "internal_milestone": "v4.2.1 Graph Engineering closure",
        "graph_maturity": (
            "production-profile-ready; preview-capabilities-explicitly-gated"
            if releasable else "configurable-preview-until-live-evidence"
        ),
        "production_profile_ready": releasable,
        "dependency_order": DEPENDENCY_ORDER,
        "gates": gates,
        "releasable": releasable,
        "policy": "A missing mandatory result blocks the corresponding recommendation; no unverified database, browser, recovery, or capacity result may be represented as passed. Evidence carrying another release version is historical and blocks the current gate.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the integrated v4.3.0 release closure manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-date", default=date.today().isoformat())
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    args = parser.parse_args()
    manifest = build_manifest(release_date=args.release_date, evidence=_load_evidence(args.evidence))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="ascii")
    print(json.dumps({"output": str(args.output), "releasable": manifest["releasable"]}, ensure_ascii=True))
    return 0 if manifest["releasable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
