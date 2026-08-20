#!/usr/bin/env python3
"""Verify that a generated release tree has not been edited after build."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile


MANIFEST_NAME = "package-files.sha256"
FORBIDDEN_PARTS = frozenset({
    ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git",
    "node_modules", "__pycache__", "runtime", "logs", "cache", "caches",
})
FORBIDDEN_NAMES = frozenset({"config.json", "config.local.json", ".env", ".env.local"})


def forbidden_package_paths(root: Path) -> list[str]:
    """Return runtime, secret, and cache paths that must never ship."""
    errors: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in FORBIDDEN_PARTS for part in relative.parts) or path.name in FORBIDDEN_NAMES:
            errors.append(relative.as_posix())
        if path.is_file() and (path.suffix in {".log", ".pid", ".sqlite", ".db"} or path.name.endswith(".secret")):
            errors.append(relative.as_posix())
    return sorted(set(errors))


def iter_package_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(root: Path) -> Path:
    target = root / MANIFEST_NAME
    lines = [
        f"{file_digest(path)}  {path.relative_to(root).as_posix()}"
        for path in iter_package_files(root)
    ]
    target.write_text("\n".join(lines) + "\n", encoding="ascii")
    return target


def verify_manifest(root: Path) -> list[str]:
    manifest = root / MANIFEST_NAME
    if not manifest.is_file():
        return [f"missing {MANIFEST_NAME}"]
    errors: list[str] = []
    expected: dict[str, str] = {}
    for line_number, line in enumerate(manifest.read_text(encoding="ascii").splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError:
            errors.append(f"invalid manifest line {line_number}")
            continue
        relative = relative.strip()
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            errors.append(f"invalid manifest path {relative!r}")
            continue
        expected[relative] = digest
        path = root / relative
        if not path.is_file():
            errors.append(f"missing generated file {relative}")
        elif file_digest(path) != digest:
            errors.append(f"generated file changed {relative}")
    actual = {path.relative_to(root).as_posix() for path in iter_package_files(root)}
    for relative in sorted(actual - set(expected)):
        errors.append(f"untracked generated file {relative}")
    for relative in sorted(set(expected) - actual):
        errors.append(f"manifest references absent file {relative}")
    return errors


def verify_archive(root: Path, archive_path: Path) -> list[str]:
    """Verify that a ZIP is an exact, complete snapshot of a package tree."""
    errors: list[str] = []
    errors.extend(f"forbidden generated path {item}" for item in forbidden_package_paths(root))
    expected: dict[str, bytes] = {}
    prefix = root.name + "/"
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = prefix + path.relative_to(root).as_posix()
        expected[relative] = path.read_bytes()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                errors.append("archive contains duplicate file entries")
            actual = set(names)
            for relative in sorted(actual - set(expected)):
                errors.append(f"archive contains unexpected file {relative}")
            for relative in sorted(set(expected) - actual):
                errors.append(f"archive is missing file {relative}")
            for relative, expected_bytes in expected.items():
                if relative not in actual:
                    continue
                if archive.read(relative) != expected_bytes:
                    errors.append(f"archive content differs for {relative}")
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"cannot read archive: {type(exc).__name__}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a generated AI Agent Infra package")
    parser.add_argument("root", type=Path)
    parser.add_argument("--archive", type=Path, help="also compare a ZIP with the generated tree")
    args = parser.parse_args()
    errors = verify_manifest(args.root)
    if args.archive:
        errors.extend(verify_archive(args.root, args.archive))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"PASS: generated package guard ({args.root})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
