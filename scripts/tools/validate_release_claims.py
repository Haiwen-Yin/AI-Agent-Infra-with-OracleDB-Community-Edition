#!/usr/bin/env python3.14
"""Fail-closed validation for a versioned release evidence manifest.

The OpenSpec status index is planning metadata. This tool deliberately checks
the evidence required to make a release claim and never treats source presence
or completed task checkboxes as release proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {
    "schema", "version", "release_date", "source_commit", "archives",
    "live_three_database", "reference_enterprise_browser", "claim_boundaries",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_commit(root: Path, value: Any) -> bool:
    commit = str(value or "").strip()
    if not commit:
        return False
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return result.returncode == 0


def validate_manifest(root: Path, manifest_path: Path, *, expected_version: str = "") -> dict[str, Any]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"passed": False, "errors": [f"manifest unreadable: {type(exc).__name__}"]}
    if not isinstance(manifest, dict):
        return {"passed": False, "errors": ["manifest must be a JSON object"]}
    missing = sorted(REQUIRED_TOP_LEVEL - set(manifest))
    errors.extend(f"required evidence missing: {key}" for key in missing)
    if manifest.get("schema") != "ai-agent-infra-release-evidence/v1":
        errors.append("unsupported release evidence schema")
    version = str(manifest.get("version") or "")
    if expected_version and version != expected_version:
        errors.append("manifest version does not match requested version")
    if not _valid_commit(root, manifest.get("source_commit")):
        errors.append("source_commit is missing or does not exist")

    archives = manifest.get("archives")
    if not isinstance(archives, list) or not archives:
        errors.append("archives must contain package hash records")
    else:
        for index, archive in enumerate(archives):
            if not isinstance(archive, dict):
                errors.append(f"archives[{index}] must be an object")
                continue
            path = root / str(archive.get("file") or "")
            expected_hash = str(archive.get("sha256") or "").lower()
            if not path.is_file():
                errors.append(f"archive is missing: {path}")
            elif len(expected_hash) != 64 or _sha256(path) != expected_hash:
                errors.append(f"archive hash mismatch: {path}")

    databases = manifest.get("live_three_database")
    if not isinstance(databases, dict) or str(databases.get("result") or "").upper() != "PASS":
        errors.append("live_three_database evidence is not PASS")
    else:
        names = {str(item).lower() for item in databases.get("databases") or []}
        if names != {"oracle", "pg", "yashandb"}:
            errors.append("live evidence must cover Oracle, PostgreSQL, and YashanDB")

    browser = manifest.get("reference_enterprise_browser")
    if not isinstance(browser, dict) or str(browser.get("result") or "").upper() != "PASS":
        errors.append("reference Enterprise browser evidence is not PASS")
    boundaries = manifest.get("claim_boundaries")
    if not isinstance(boundaries, dict) or not boundaries.get("not_claimed"):
        errors.append("claim_boundaries.not_claimed is required")

    return {"passed": not errors, "errors": errors, "version": version,
            "source_commit": manifest.get("source_commit"), "archives": len(archives or [])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--version", default="")
    args = parser.parse_args()
    result = validate_manifest(args.root.resolve(), args.manifest.resolve(), expected_version=args.version)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
