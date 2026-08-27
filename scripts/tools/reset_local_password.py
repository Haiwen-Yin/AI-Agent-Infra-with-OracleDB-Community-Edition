#!/usr/bin/env python3.14
"""Recover one local human password through the governed reset transaction."""
from __future__ import annotations

import argparse
import os

from bootstrap_deployment_agent import _masked_getpass
from lib import security_lifecycle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="Local username to recover")
    args = parser.parse_args()
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise SystemExit("password recovery must be run by root")
    password = _masked_getpass("New password: ")
    confirmation = _masked_getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("password confirmation does not match")
    issued = security_lifecycle.issue_password_reset(
        args.username, reason="local operator account recovery"
    )
    token = issued.get("token")
    if not issued.get("issued") or not token:
        raise SystemExit("eligible local account was not found")
    security_lifecycle.consume_password_reset(
        str(token), password, reason="local operator account recovery"
    )
    print("Local password reset completed; existing sessions were revoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
