"""Minimal SCM adapter boundary for governed software delivery.

Adapters accept repository references and credential *references* only.  The
Web service never accepts, stores or returns SCM tokens.  Local Git inspection
is metadata-only and is intended for a leased Worker or explicit operator
diagnostic, not a browser-side checkout.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from . import sdd_api


SUPPORTED_ADAPTERS = frozenset({"LOCAL_GIT", "GITHUB"})


def register_connection(adapter_kind: str, repository_ref: str, *, credential_reference: Optional[str] = None,
                        policy: Optional[Dict[str, Any]] = None, actor: Optional[str] = None) -> Dict[str, Any]:
    kind = str(adapter_kind or "").upper()
    if kind not in SUPPORTED_ADAPTERS:
        raise ValueError("SCM_ADAPTER_UNSUPPORTED")
    if not str(repository_ref or "").strip() or any(token in str(credential_reference or "").lower() for token in ("token=", "password=", "secret=")):
        raise ValueError("SCM_CONNECTION_INVALID")
    connection_id = sdd_api._id("SDD_SCM")
    sdd_api.execute(
        "INSERT INTO CX_SDD_SCM_CONNECTIONS (CONNECTION_ID,ADAPTER_KIND,REPOSITORY_REF,CREDENTIAL_REFERENCE,POLICY_JSON,STATUS,CREATED_BY) "
        "VALUES (:id,:kind,:repo,:credential,:policy,'ACTIVE',:actor)",
        {"id": connection_id, "kind": kind, "repo": repository_ref[:2048], "credential": credential_reference,
         "policy": sdd_api._json(policy or {}), "actor": sdd_api._actor(actor)},
    )
    return {"connection_id": connection_id, "adapter_kind": kind, "repository_ref": repository_ref, "credential_reference_set": bool(credential_reference)}


def inspect_local_git(repository_ref: str) -> Dict[str, Any]:
    path = Path(repository_ref).resolve()
    if not path.is_dir() or not (path / ".git").exists():
        raise ValueError("SCM_LOCAL_GIT_REPOSITORY_REQUIRED")
    def command(*args: str) -> str:
        return subprocess.run(["git", "-C", str(path), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10).stdout.strip()
    head = command("rev-parse", "HEAD")
    branch = command("rev-parse", "--abbrev-ref", "HEAD")
    porcelain = command("status", "--porcelain=v1")
    return {"adapter_kind": "LOCAL_GIT", "repository_ref": str(path), "head": head, "branch": branch,
            "clean": not bool(porcelain), "state_digest": hashlib.sha256((head + "\n" + porcelain).encode("utf-8")).hexdigest()}

