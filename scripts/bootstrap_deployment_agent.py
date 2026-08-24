#!/usr/bin/env python3.14
"""Package-local Bootstrap Deployment Agent command entry point."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lib.deployment_orchestrator import DeploymentError, run


def _initial_admin_password(command: str, password_file: Path | None) -> str:
    if command not in {"initialize", "resume"}:
        return ""
    if password_file is not None:
        fd = -1
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(password_file, flags)
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise DeploymentError("administrator password file must be a regular file owned by the current user")
            if metadata.st_mode & 0o077:
                raise DeploymentError("administrator password file permissions must be 0600 or stricter")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                fd = -1
                password = stream.read().rstrip("\r\n")
        except OSError as exc:
            raise DeploymentError("administrator password file is unreadable") from exc
        finally:
            if fd >= 0:
                os.close(fd)
        if not password:
            raise DeploymentError("administrator password file is empty")
        return password
    if not sys.stdin.isatty():
        raise DeploymentError("--admin-password-file is required for non-interactive initialization")
    password = getpass.getpass("Initial admin password: ")
    confirmation = getpass.getpass("Confirm initial admin password: ")
    if password != confirmation:
        raise DeploymentError("administrator password confirmation does not match")
    return password


def main() -> int:
    parser = argparse.ArgumentParser(description="Chuanxu Bootstrap Deployment Agent")
    parser.add_argument("command", choices=("initialize", "upgrade", "resume", "status", "verify"))
    parser.add_argument("--database", choices=("oracle", "pg", "yashandb"), required=True)
    parser.add_argument("--edition", choices=("community", "enterprise"), required=True)
    parser.add_argument("--config", type=Path, default=SCRIPT_ROOT.parent / "config.json")
    parser.add_argument("--version", default="", help="must match the packaged baseline manifest")
    parser.add_argument("--run-id", default="", help="required to resume a previous local deployment journal")
    parser.add_argument("--admin-password-file", type=Path,
                        help="0600 file used only for initialize/resume; the plaintext is never persisted")
    parser.add_argument("--backup-evidence", type=Path,
                        help="recoverable backup manifest required for initialize/upgrade/resume")
    args = parser.parse_args()
    try:
        admin_password = _initial_admin_password(args.command, args.admin_password_file)
        result = run(args.command, database=args.database, edition=args.edition, config_path=args.config,
                     root=SCRIPT_ROOT.parent, run_id=args.run_id, target_version=args.version,
                     bootstrap_admin_password=admin_password, backup_evidence=args.backup_evidence)
    except DeploymentError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0 if str(result.get("status") or "") not in {"FAILED", "FAILED_MANUAL_ACTION_REQUIRED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
