#!/usr/bin/env python3.14
"""Assemble four-week POC acceptance evidence from release reports.

This tool does not infer customer success.  It verifies that the technical
acceptance items are backed by existing, timestamped evidence and keeps
efficiency measurements and unavailable runtime checks outside the mandatory
acceptance set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"EvidenceObjectRequired:{path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence(path: Path, label: str) -> dict[str, Any]:
    return {"label": label, "file": path.name, "sha256": _sha256(path)}


def _skill_contract_ok(path: Path) -> bool:
    if not path.exists() or path.name != "SKILL.md":
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    required = ("Skill-first", "registration", "SKILL.md", "/api/health")
    return all(term.lower() in text.lower() for term in required)


def _governance_checks(payload: dict[str, Any], names: set[str]) -> bool:
    results = payload.get("results") or []
    return (
        len(results) == 3
        and all(
            item.get("passed") is True
            and names <= set((item.get("checks") or {}).keys())
            and all(bool(value) for value in (item.get("checks") or {}).values())
            for item in results
        )
    )


def build_report(manifest_path: Path, clean_path: Path, mode_path: Path,
                 governance_path: Path, readiness_path: Path | None = None,
                 skill_paths: list[Path] | None = None) -> dict[str, Any]:
    manifest = _load(manifest_path)
    clean = _load(clean_path)
    modes = _load(mode_path)
    governance = _load(governance_path)
    evidence_files = [manifest_path, clean_path, mode_path, governance_path]
    if readiness_path is not None:
        evidence_files.append(readiness_path)
    mandatory = [
        {
            "id": "deployment",
            "title": "Platform deployment",
            "passed": clean.get("passed") is True and clean.get("deployments_executed") == 6,
            "evidence": [_evidence(clean_path, "six clean deployments")],
        },
        {
            "id": "agent_inventory",
            "title": "Registered Agent inventory",
            "passed": _governance_checks(governance, {"registration:primary:active", "registration:authenticate"}),
            "evidence": [_evidence(governance_path, "registered identity and authentication")],
        },
        {
            "id": "status_activity",
            "title": "Agent status and activity visibility",
            "passed": (
                modes.get("passed") is True
                and modes.get("targets_executed") == 18
                and _governance_checks(governance, {"registration:heartbeat"})
            ),
            "evidence": [
                _evidence(mode_path, "18 operating modes"),
                _evidence(governance_path, "heartbeat and lifecycle"),
            ],
        },
        {
            "id": "audit_trace",
            "title": "One scoped audit trace",
            "passed": _governance_checks(governance, {"audit:scoped-export", "audit:export-integrity", "audit:bounded-detail"}),
            "evidence": [_evidence(governance_path, "bounded audit and scoped export")],
        },
        {
            "id": "disable_or_revoke",
            "title": "Agent disable and access revocation",
            "passed": _governance_checks(governance, {"emergency:agent-disabled", "emergency:grant-revoked", "emergency:retry-same-operation"}),
            "evidence": [_evidence(governance_path, "durable emergency control")],
        },
    ]

    compatibility = []
    skill_paths = skill_paths or []
    contract_ok = all(_skill_contract_ok(path) for path in skill_paths) if skill_paths else False
    for runtime in ("OpenClaw", "Hermes Agent", "generic SKILL.md client"):
        compatibility.append({
            "runtime": runtime,
            "validation_scope": "Skill contract and documented HTTP/MCP/CLI operations",
            "contract_validated": contract_ok,
            "native_runtime_version": None,
            "native_runtime_execution": False,
            "note": "Native runtime executable/version was not present in this release environment.",
        })

    optional = [
        {
            "id": "token_efficiency",
            "title": "Token and efficiency observation",
            "status": "OBSERVED",
            "acceptance_target": False,
            "evidence": [_evidence(manifest_path, "bounded benchmark claim")],
        },
    ]
    skipped = [
        {
            "id": "native_runtime_execution",
            "title": "Native OpenClaw/Hermes executable validation",
            "reason": "The named external runtimes were not installed in the release environment; only the framework-neutral Skill contract was checked.",
        },
        {
            "id": "post_review",
            "title": "Post-review workflow",
            "reason": "Optional and controlled by the customer approval policy; not required for the standard technical POC acceptance.",
        },
    ]
    passed = manifest.get("passed") is True and all(item["passed"] for item in mandatory)
    return {
        "schema": "ai-agent-infra-poc-evidence/v1",
        "version": manifest.get("version"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "four-week technical POC acceptance",
        "passed": passed,
        "mandatory": mandatory,
        "compatibility": compatibility,
        "optional_observations": optional,
        "skipped": skipped,
        "evidence_files": [_evidence(path, path.name) for path in evidence_files],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate bounded POC acceptance evidence.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--clean", type=Path, required=True)
    parser.add_argument("--modes", type=Path, required=True)
    parser.add_argument("--governance", type=Path, required=True)
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--skill", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_report(args.manifest, args.clean, args.modes, args.governance, args.readiness, args.skill)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    print(json.dumps({"output": str(args.output), "passed": payload["passed"]}, ensure_ascii=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
