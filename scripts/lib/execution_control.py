"""Durable, approval-gated execution control plane."""

import hashlib
import ipaddress
import json
import os
import resource
import secrets
import socket
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .connection import execute, execute_query, execute_query_one

MAX_OUTPUT_BYTES = 64 * 1024
MAX_HTTP_BYTES = 2 * 1024 * 1024
DEFAULT_ALLOWED_COMMANDS = {"git", "python3.14"}


def _id(prefix: str) -> str:
    return prefix + secrets.token_hex(16)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def enqueue_job(
    job_type: str,
    payload: Dict[str, Any],
    agent_id: str,
    *,
    idempotency_key: Optional[str] = None,
    requires_approval: bool = True,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    if not agent_id:
        raise ValueError("agent_id is required")
    if not idempotency_key:
        canonical = _json({"type": job_type, "payload": payload, "agent": agent_id})
        idempotency_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = execute_query_one(
        "SELECT * FROM EXECUTION_JOBS WHERE IDEMPOTENCY_KEY = :key",
        {"key": idempotency_key},
    )
    if existing:
        return dict(existing)

    job_id = _id("JOB_")
    status = "WAITING_APPROVAL" if requires_approval else "PENDING"
    execute(
        """INSERT INTO EXECUTION_JOBS
           (JOB_ID, JOB_TYPE, STATUS, AGENT_ID, PAYLOAD_JSON, IDEMPOTENCY_KEY,
            MAX_ATTEMPTS, REQUIRES_APPROVAL, CANCEL_REQUESTED, CREATED_AT, UPDATED_AT)
           VALUES (:job_id, :job_type, :status, :agent_id, :payload, :key,
                   :max_attempts, :approval, 'N', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        {
            "job_id": job_id,
            "job_type": job_type,
            "status": status,
            "agent_id": agent_id,
            "payload": _json(payload),
            "key": idempotency_key,
            "max_attempts": max(1, min(int(max_attempts), 10)),
            "approval": "Y" if requires_approval else "N",
        },
    )
    _audit(job_id, "CREATED", agent_id, {"status": status})
    return get_job(job_id)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one("SELECT * FROM EXECUTION_JOBS WHERE JOB_ID = :id", {"id": job_id})
    if not row:
        return None
    result = dict(row)
    for field in ("payload_json", "result_json"):
        if isinstance(result.get(field), str):
            try:
                result[field] = json.loads(result[field])
            except json.JSONDecodeError:
                pass
    return result


def decide_job(job_id: str, approved: bool, decided_by: str, reason: str = "") -> bool:
    status = "PENDING" if approved else "REJECTED"
    affected = execute(
        """UPDATE EXECUTION_JOBS
              SET STATUS = :status, APPROVED_BY = :by, APPROVED_AT = CURRENT_TIMESTAMP,
                  ERROR_MESSAGE = :reason, UPDATED_AT = CURRENT_TIMESTAMP
            WHERE JOB_ID = :id AND STATUS = 'WAITING_APPROVAL'""",
        {"status": status, "by": decided_by, "reason": reason or None, "id": job_id},
    )
    if affected:
        _audit(job_id, "APPROVED" if approved else "REJECTED", decided_by, {"reason": reason})
    return affected > 0


def cancel_job(job_id: str, requested_by: str) -> bool:
    affected = execute(
        """UPDATE EXECUTION_JOBS SET CANCEL_REQUESTED = 'Y',
                  STATUS = CASE WHEN STATUS IN ('PENDING','WAITING_APPROVAL','RETRY')
                                THEN 'CANCELLED' ELSE STATUS END,
                  UPDATED_AT = CURRENT_TIMESTAMP
            WHERE JOB_ID = :id
              AND STATUS NOT IN ('SUCCEEDED','FAILED','CANCELLED','REJECTED')""",
        {"id": job_id},
    )
    if affected:
        _audit(job_id, "CANCEL_REQUESTED", requested_by, {})
    return affected > 0


def claim_job(worker_id: str, lease_seconds: int = 60) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    execute(
        """UPDATE EXECUTION_JOBS SET STATUS = 'RETRY', LEASE_TOKEN = NULL,
                  LEASE_OWNER = NULL, LEASE_UNTIL = NULL, UPDATED_AT = CURRENT_TIMESTAMP
            WHERE STATUS = 'RUNNING' AND LEASE_UNTIL < :now
              AND CANCEL_REQUESTED = 'N' AND ATTEMPT_COUNT < MAX_ATTEMPTS""",
        {"now": now},
    )
    candidates = execute_query(
        """SELECT JOB_ID FROM EXECUTION_JOBS
            WHERE STATUS IN ('PENDING','RETRY') AND CANCEL_REQUESTED = 'N'
              AND ATTEMPT_COUNT < MAX_ATTEMPTS
            ORDER BY CREATED_AT ASC FETCH FIRST 10 ROWS ONLY"""
    )
    for candidate in candidates:
        job_id = candidate.get("job_id")
        token = secrets.token_urlsafe(24)
        lease_until = now + timedelta(seconds=max(10, min(lease_seconds, 3600)))
        affected = execute(
            """UPDATE EXECUTION_JOBS
                  SET STATUS = 'RUNNING', LEASE_TOKEN = :token, LEASE_OWNER = :owner,
                      LEASE_UNTIL = :lease_until, ATTEMPT_COUNT = ATTEMPT_COUNT + 1,
                      UPDATED_AT = CURRENT_TIMESTAMP
                WHERE JOB_ID = :id AND STATUS IN ('PENDING','RETRY')
                  AND CANCEL_REQUESTED = 'N'""",
            {"token": token, "owner": worker_id, "lease_until": lease_until, "id": job_id},
        )
        if affected:
            attempt_id = _id("ATT_")
            execute(
                """INSERT INTO EXECUTION_ATTEMPTS
                   (ATTEMPT_ID, JOB_ID, ATTEMPT_NUMBER, LEASE_TOKEN, WORKER_ID, STATUS, STARTED_AT)
                   SELECT :attempt_id, JOB_ID, ATTEMPT_COUNT, :token, :worker, 'RUNNING', CURRENT_TIMESTAMP
                     FROM EXECUTION_JOBS WHERE JOB_ID = :id""",
                {"attempt_id": attempt_id, "token": token, "worker": worker_id, "id": job_id},
            )
            return get_job(job_id)
    return None


def renew_lease(job_id: str, lease_token: str, lease_seconds: int = 60) -> bool:
    lease_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=lease_seconds)
    return execute(
        """UPDATE EXECUTION_JOBS SET LEASE_UNTIL = :until, UPDATED_AT = CURRENT_TIMESTAMP
            WHERE JOB_ID = :id AND LEASE_TOKEN = :token AND STATUS = 'RUNNING'
              AND CANCEL_REQUESTED = 'N'""",
        {"until": lease_until, "id": job_id, "token": lease_token},
    ) > 0


def complete_job(job_id: str, lease_token: str, result: Dict[str, Any]) -> bool:
    affected = execute(
        """UPDATE EXECUTION_JOBS SET STATUS = 'SUCCEEDED', RESULT_JSON = :result,
                  LEASE_TOKEN = NULL, LEASE_OWNER = NULL, LEASE_UNTIL = NULL,
                  COMPLETED_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP
            WHERE JOB_ID = :id AND LEASE_TOKEN = :token AND STATUS = 'RUNNING'
              AND CANCEL_REQUESTED = 'N'""",
        {"result": _json(result), "id": job_id, "token": lease_token},
    )
    if affected:
        _finish_attempt(job_id, lease_token, "SUCCEEDED", result, None)
        _audit(job_id, "SUCCEEDED", "worker", {})
    return affected > 0


def fail_job(job_id: str, lease_token: str, error: str, retryable: bool = True) -> bool:
    job = get_job(job_id)
    if not job or job.get("lease_token") != lease_token or job.get("status") != "RUNNING":
        return False
    retry = retryable and int(job.get("attempt_count", 0)) < int(job.get("max_attempts", 1))
    status = "RETRY" if retry else "FAILED"
    affected = execute(
        """UPDATE EXECUTION_JOBS SET STATUS = :status, ERROR_MESSAGE = :error,
                  LEASE_TOKEN = NULL, LEASE_OWNER = NULL, LEASE_UNTIL = NULL,
                  COMPLETED_AT = CASE WHEN :status = 'FAILED' THEN CURRENT_TIMESTAMP ELSE NULL END,
                  UPDATED_AT = CURRENT_TIMESTAMP
            WHERE JOB_ID = :id AND LEASE_TOKEN = :token AND STATUS = 'RUNNING'""",
        {"status": status, "error": error[:2000], "id": job_id, "token": lease_token},
    )
    if affected:
        _finish_attempt(job_id, lease_token, status, None, error)
        _audit(job_id, status, "worker", {"error": error[:500]})
    return affected > 0


def run_worker_once(worker_id: str = "worker") -> Optional[Dict[str, Any]]:
    job = claim_job(worker_id)
    if not job:
        return None
    job_id = job["job_id"]
    token = job["lease_token"]
    payload = job.get("payload_json") or {}
    try:
        if job["job_type"] in ("COMMAND", "LOOP_TEST", "LOOP_DIFF", "HOOK_SCRIPT"):
            result = _run_command(payload)
        elif job["job_type"] in ("HTTP", "TOOL_HTTP", "HOOK_WEBHOOK", "HOOK_MCP"):
            result = _run_http(payload)
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
        complete_job(job_id, token, result)
    except Exception as exc:
        fail_job(job_id, token, str(exc), retryable=True)
    return get_job(job_id)


def _run_command(payload: Dict[str, Any]) -> Dict[str, Any]:
    argv = payload.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("Command payload requires a non-empty argv string array")
    executable = Path(argv[0]).name
    allowed = set(os.environ.get("AI_AGENT_ALLOWED_COMMANDS", "").split(",")) - {""}
    allowed = allowed or DEFAULT_ALLOWED_COMMANDS
    if executable not in allowed:
        raise PermissionError(f"Executable is not allowed: {executable}")
    timeout = max(1, min(int(payload.get("timeout", 120)), 900))
    project_root = Path(os.environ.get("AI_AGENT_WORKSPACE_ROOT", os.getcwd())).resolve()
    relative_cwd = payload.get("cwd", ".")
    cwd = (project_root / relative_cwd).resolve()
    if cwd != project_root and project_root not in cwd.parents:
        raise ValueError("Command cwd escapes the configured workspace")

    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 1))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

    completed = subprocess.run(
        argv,
        cwd=cwd,
        input=str(payload.get("stdin", "")),
        text=True,
        capture_output=True,
        timeout=timeout,
        shell=False,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())},
        preexec_fn=limits,
    )
    return {
        "exit_code": completed.returncode,
        "stdout": (completed.stdout or "")[-MAX_OUTPUT_BYTES:],
        "stderr": (completed.stderr or "")[-MAX_OUTPUT_BYTES:],
    }


def validate_outbound_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only credential-free HTTP(S) URLs are allowed")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("URL host did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError(f"Non-public destination is blocked: {ip}")
    return url


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_outbound_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _run_http(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = validate_outbound_url(str(payload.get("url", "")))
    method = str(payload.get("method", "POST")).upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ValueError("HTTP method is not allowed")
    headers = payload.get("headers") or {"Content-Type": "application/json"}
    body = payload.get("body")
    data = body.encode("utf-8") if isinstance(body, str) else (_json(body).encode("utf-8") if body is not None else None)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(_ValidatedRedirectHandler())
    with opener.open(request, timeout=max(1, min(int(payload.get("timeout", 30)), 120))) as response:
        content = response.read(MAX_HTTP_BYTES + 1)
        if len(content) > MAX_HTTP_BYTES:
            raise ValueError("HTTP response exceeds size limit")
        return {"status_code": response.status, "body": content.decode("utf-8", "replace")}


def _finish_attempt(job_id, lease_token, status, result, error):
    execute(
        """UPDATE EXECUTION_ATTEMPTS SET STATUS = :status, RESULT_JSON = :result,
                  ERROR_MESSAGE = :error, COMPLETED_AT = CURRENT_TIMESTAMP
            WHERE JOB_ID = :job_id AND LEASE_TOKEN = :token AND STATUS = 'RUNNING'""",
        {"status": status, "result": _json(result) if result is not None else None,
         "error": error[:2000] if error else None, "job_id": job_id, "token": lease_token},
    )


def _audit(job_id: str, action: str, actor: str, detail: Dict[str, Any]):
    execute(
        """INSERT INTO EXECUTION_AUDIT
           (AUDIT_ID, JOB_ID, ACTION_TYPE, ACTOR_ID, DETAIL_JSON, CREATED_AT)
           VALUES (:id, :job, :action, :actor, :detail, CURRENT_TIMESTAMP)""",
        {"id": _id("AUD_"), "job": job_id, "action": action,
         "actor": actor, "detail": _json(detail)},
    )
