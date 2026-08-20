"""Fail-closed version consistency checks for v4.4.9 packages and evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError:
        return ""


def validate_version_consistency(root: Path, expected: str | None = None, manifest: dict[str, Any] | None = None) -> list[str]:
    version = expected or _read(root / "VERSION")
    errors: list[str] = []
    if _read(root / "VERSION") != version:
        errors.append("VERSION does not match expected version")
    web_root = root / "shared" / "web" if (root / "shared" / "web").is_dir() else root / "web"
    try:
        package = json.loads((web_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        package = {}
    if str(package.get("version") or "") != version:
        errors.append("frontend package version does not match VERSION")
    if manifest is not None and str(manifest.get("version") or "") != version:
        errors.append("release manifest version does not match VERSION")
    return errors
