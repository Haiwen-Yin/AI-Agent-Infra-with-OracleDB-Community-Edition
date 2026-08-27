#!/usr/bin/env python3.14
"""Package-local Bootstrap Deployment Agent command entry point."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import termios
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from lib.deployment_orchestrator import DeploymentError, run


def _masked_getpass(prompt: str) -> str:
    """Read a TTY secret while showing one star per accepted character."""
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    masked = termios.tcgetattr(fd)
    masked[3] &= ~(termios.ECHO | termios.ICANON)
    masked[6][termios.VMIN] = 1
    masked[6][termios.VTIME] = 0
    chars: list[str] = []
    sys.stderr.write(prompt)
    sys.stderr.flush()
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, masked)
        while True:
            char = sys.stdin.read(1)
            if char in {"\r", "\n"}:
                break
            if char in {"\b", "\x7f"}:
                if chars:
                    chars.pop()
                    sys.stderr.write("\b \b")
                    sys.stderr.flush()
                continue
            if char == "\x04":
                if not chars:
                    break
                continue
            chars.append(char)
            sys.stderr.write("*")
            sys.stderr.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
        sys.stderr.write("\n")
        sys.stderr.flush()
    return "".join(chars)


def _initial_admin_password(command: str, password_file: Path | None) -> str:
    if command not in {"initialize", "resume"}:
        return ""
    # A resume may occur after the administrator was already committed but
    # before postflight state was finalized. The orchestrator verifies that
    # durable state before allowing a password-free continuation.
    if command == "resume" and password_file is None:
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
    password = _masked_getpass("Initial admin password: ")
    confirmation = _masked_getpass("Confirm initial admin password: ")
    if password != confirmation:
        raise DeploymentError("administrator password confirmation does not match")
    return password


def _database_backup_confirmation(command: str, confirmed: bool) -> bool:
    if command != "upgrade" or confirmed:
        return confirmed
    if not sys.stdin.isatty():
        raise DeploymentError(
            "--confirm-database-backup is required for non-interactive upgrade"
        )
    print(
        "Upgrade changes an existing database. Backup and recovery are managed "
        "by the selected database environment and cannot be verified by this client."
    )
    answer = input("Type UPGRADE to confirm database backup/recovery responsibility: ").strip()
    if answer != "UPGRADE":
        raise DeploymentError("upgrade confirmation was not accepted")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Chuanxu Bootstrap Deployment Agent")
    parser.add_argument("command", choices=("initialize", "upgrade", "resume", "status", "verify"))
    parser.add_argument("--database", choices=("oracle", "pg", "yashandb"), required=True)
    parser.add_argument("--edition", choices=("community", "enterprise"), required=True)
    parser.add_argument("--config", type=Path, default=SCRIPT_ROOT.parent / "config.json")
    parser.add_argument("--version", default="", help="must match the packaged baseline manifest")
    parser.add_argument("--run-id", default="", help="required to resume a previous local deployment journal")
    parser.add_argument("--admin-password-file", type=Path,
                        help="0600 file required for initialize and for resume before administrator setup; the plaintext is never persisted")
    parser.add_argument(
        "--confirm-database-backup", action="store_true",
        help="confirm database-side backup/recovery responsibility for non-interactive upgrade",
    )
    args = parser.parse_args()
    try:
        admin_password = _initial_admin_password(args.command, args.admin_password_file)
        database_backup_confirmed = _database_backup_confirmation(
            args.command, args.confirm_database_backup,
        )
        result = run(args.command, database=args.database, edition=args.edition, config_path=args.config,
                     root=SCRIPT_ROOT.parent, run_id=args.run_id, target_version=args.version,
                     bootstrap_admin_password=admin_password,
                     database_backup_confirmed=database_backup_confirmed)
    except DeploymentError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2, default=str))
    return 0 if str(result.get("status") or "") not in {"FAILED", "FAILED_MANUAL_ACTION_REQUIRED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
