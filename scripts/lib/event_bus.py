"""AI Agent Infra v4.0.1 - Enterprise Edition - Event Bus + Hook Execution

Event publishing, subscription management, and LOOP_HOOKS execution engine.
Agent capability discovery.

Tables: EVENT_LOG, EVENT_SUBSCRIPTIONS, AGENT_CAPABILITY_INDEX, LOOP_HOOKS
"""

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert,
    execute_insert_returning_id,
    sanitize_row,
)

logger = logging.getLogger(__name__)

_thread_local = threading.local()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    return sanitize_row(row)


def publish_event(
    event_type: str,
    source_id: Optional[str] = None,
    source_type: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    try:
        return execute_insert_returning_id(
            """INSERT INTO EVENT_LOG (EVENT_ID, EVENT_TYPE, SOURCE_ID, SOURCE_TYPE, PAYLOAD)
               VALUES (AI_NEW_ID(), :etype, :sid, :stype, :payload)
               RETURNING EVENT_ID INTO :ret_id""",
            {
                "etype": event_type, "sid": source_id, "stype": source_type,
                "payload": json.dumps(payload) if payload else None,
            },
        )
    except Exception as e:
        # Delivery / persistence failure — route to dead letter queue so the
        # event is not lost. We avoid re-entering publish_event to prevent
        # infinite recursion by writing directly to EVENT_DEAD_LETTER.
        logger.error("publish_event failed for %s: %s", event_type, e)
        try:
            send_to_dead_letter(
                event_id=None,
                agent_id=source_id if source_type == "AGENT" else None,
                event_type=event_type,
                payload=payload or {},
                reason=f"publish_event failure: {e}",
            )
        except Exception as dlq_err:
            logger.error("Failed to send failed event to dead letter: %s", dlq_err)
        return None


def subscribe_agent(
    agent_id: str,
    event_type: str,
    filter_pattern: Optional[str] = None,
) -> str:
    existing = execute_query_one(
        "SELECT SUB_ID FROM EVENT_SUBSCRIPTIONS WHERE AGENT_ID = :aid AND EVENT_TYPE = :etype",
        {"aid": agent_id, "etype": event_type},
    )
    if existing:
        return existing["sub_id"]

    return execute_insert_returning_id(
        """INSERT INTO EVENT_SUBSCRIPTIONS (SUB_ID, AGENT_ID, EVENT_TYPE, FILTER_PATTERN)
           VALUES (AI_NEW_ID(), :aid, :etype, :filter) RETURNING SUB_ID INTO :ret_id""",
        {"aid": agent_id, "etype": event_type, "filter": filter_pattern},
    )


def unsubscribe_agent(agent_id: str, event_type: str) -> bool:
    affected = execute(
        "DELETE FROM EVENT_SUBSCRIPTIONS WHERE AGENT_ID = :aid AND EVENT_TYPE = :etype",
        {"aid": agent_id, "etype": event_type},
    )
    return affected > 0


def get_pending_events(agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT e.* FROM EVENT_LOG e
           INNER JOIN EVENT_SUBSCRIPTIONS s ON s.EVENT_TYPE = e.EVENT_TYPE
           WHERE s.AGENT_ID = :aid AND s.ENABLED = 'Y'
             AND e.CREATED_AT > (
               SELECT MAX(CREATED_AT) FROM EVENT_LOG e2
               WHERE e2.SOURCE_ID = :aid AND e2.EVENT_TYPE = 'ACK'
             )
           ORDER BY e.CREATED_AT DESC
           FETCH FIRST :limit ROWS ONLY""",
        {"aid": agent_id, "limit": limit},
    )
    return [_row_to_dict(r) for r in rows]


def acknowledge_event(event_id: str, agent_id: str) -> bool:
    ack_id = publish_event("ACK", source_id=agent_id, source_type="AGENT",
                          payload={"acknowledged_event": event_id})
    return ack_id is not None


def get_subscriptions(agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if agent_id:
        rows = execute_query(
            "SELECT * FROM EVENT_SUBSCRIPTIONS WHERE AGENT_ID = :aid ORDER BY CREATED_AT",
            {"aid": agent_id},
        )
    else:
        rows = execute_query(
            "SELECT * FROM EVENT_SUBSCRIPTIONS ORDER BY CREATED_AT",
        )
    return [_row_to_dict(r) for r in rows]


def execute_hooks(loop_id: str, hook_event: str, context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows = execute_query(
        "SELECT * FROM LOOP_HOOKS WHERE LOOP_ID = :lid AND HOOK_EVENT = :event AND ENABLED = 'Y' ORDER BY PRIORITY",
        {"lid": loop_id, "event": hook_event},
    )
    results: List[Dict[str, Any]] = []
    context = context or {}

    for hook in rows:
        hook_type = hook.get("hook_type", "LOG")
        hook_config = hook.get("hook_config", "{}")
        try:
            if hook_type in ("WEBHOOK", "SCRIPT", "MCP_CALL"):
                from .execution_control import enqueue_job
                config = json.loads(hook_config) if isinstance(hook_config, str) else dict(hook_config or {})
                if hook_type == "WEBHOOK":
                    job_type = "HOOK_WEBHOOK"
                    payload = {
                        "url": config.get("url"), "method": "POST",
                        "headers": config.get("headers", {"Content-Type": "application/json"}),
                        "body": context, "timeout": config.get("timeout", 30),
                    }
                elif hook_type == "SCRIPT":
                    import shlex
                    argv = config.get("argv")
                    if not argv:
                        argv = shlex.split(config.get("command", "")) + list(config.get("args", []))
                    job_type = "HOOK_SCRIPT"
                    payload = {"argv": argv, "stdin": json.dumps(context),
                               "timeout": config.get("timeout", 60), "cwd": config.get("cwd", ".")}
                else:
                    job_type = "HOOK_MCP"
                    payload = {
                        "url": config.get("server_url", "").rstrip("/") + "/messages",
                        "method": "POST",
                        "body": {"tool_name": config.get("tool_name"),
                                 "arguments": {**config.get("arguments", {}), "_context": context}},
                    }
                job = enqueue_job(
                    job_type, payload, context.get("agent_id") or "system",
                    idempotency_key=f"hook:{hook.get('hook_id')}:{hook_event}:{context.get('run_id', '')}:{context.get('iteration_id', '')}",
                    requires_approval=True,
                    max_attempts=int(config.get("retries", 3)),
                )
                results.append({"hook_id": hook.get("hook_id"), "type": hook_type,
                                "status": "QUEUED", "job_id": job.get("job_id")})
                continue
            elif hook_type == "NOTIFICATION":
                _execute_notification(hook, context)
            elif hook_type == "LOG":
                logger.info("Hook %s fired for loop %s event %s: %s",
                           hook.get("hook_id"), loop_id, hook_event, hook_config)
            results.append({"hook_id": hook.get("hook_id"), "type": hook_type, "status": "OK"})
        except Exception as e:
            logger.error("Hook %s failed: %s", hook.get("hook_id"), e)
            results.append({"hook_id": hook.get("hook_id"), "type": hook_type, "status": "FAILED", "error": str(e)})
    return results


def _execute_webhook(config_str: str, payload: str):
    """Legacy worker-only helper; API code must enqueue through execute_hooks."""
    import urllib.request
    import urllib.error
    config = json.loads(config_str) if config_str else {}
    url = config.get("url")
    if not url:
        return
    headers = config.get("headers", {"Content-Type": "application/json"})
    timeout = config.get("timeout", 30)
    max_retries = config.get("retries", 3)

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=payload.encode("utf-8"),
                                         headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=timeout)
            return
        except urllib.error.HTTPError as e:
            logger.warning("Webhook %s attempt %d failed: HTTP %d", url, attempt + 1, e.code)
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)
            else:
                raise
        except urllib.error.URLError as e:
            logger.warning("Webhook %s attempt %d failed: %s", url, attempt + 1, e)
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)
            else:
                raise


def _execute_script(config_str: str, payload: str):
    """Legacy worker-only helper; API code must enqueue through execute_hooks."""
    import subprocess
    config = json.loads(config_str) if config_str else {}
    cmd = config.get("command")
    if not cmd:
        return
    args = config.get("args", [])
    timeout = config.get("timeout", 60)
    try:
        if isinstance(args, list) and args:
            subprocess.run(args, timeout=timeout, input=payload.encode(),
                           capture_output=True, check=True)
        else:
            subprocess.run(cmd.split(), timeout=timeout, input=payload.encode(),
                           capture_output=True, check=True)
    except subprocess.TimeoutExpired:
        logger.error("Script timeout after %ds: %s", timeout, cmd)
        raise
    except subprocess.CalledProcessError as e:
        logger.error("Script failed with code %d: %s", e.returncode, e.stderr)
        raise


def _execute_notification(hook: Dict[str, Any], context: Optional[Dict[str, Any]]):
    publish_event(
        event_type="HOOK_NOTIFICATION",
        source_id=hook.get("hook_id"),
        source_type="LOOP_HOOK",
        payload={"hook_event": hook.get("hook_event"), "context": context},
    )


def _execute_mcp_call(config_str: str, payload: str):
    """Execute an MCP tool call as a hook callback.

    Config should contain:
        - server_url: URL of the MCP server (for SSE mode)
        - tool_name: Name of the MCP tool to call
        - arguments: Arguments dict to pass to the tool
    Or for stdio mode:
        - command: Command to start the MCP server
        - tool_name: Name of the MCP tool to call
        - arguments: Arguments dict to pass to the tool
    """
    config = json.loads(config_str) if config_str else {}
    tool_name = config.get("tool_name", "")
    arguments = config.get("arguments", {})
    if payload:
        try:
            ctx = json.loads(payload)
            arguments.setdefault("_context", ctx)
        except (json.JSONDecodeError, TypeError):
            pass

    server_url = config.get("server_url", "")
    command = config.get("command", "")

    if server_url:
        try:
            import urllib.request
            data = json.dumps({"tool_name": tool_name, "arguments": arguments}).encode()
            req = urllib.request.Request(
                f"{server_url}/messages",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                logger.info("MCP call %s result: %s", tool_name, str(result)[:200])
        except Exception as e:
            logger.error("MCP call %s failed: %s", tool_name, e)
    elif command:
        logger.info("MCP stdio call %s (not yet supported in sync mode)", tool_name)
    else:
        logger.info("MCP call %s with no server configured", tool_name)


def register_capability(agent_id: str, capability: str, confidence: float = 1.0) -> str:
    existing = execute_query_one(
        "SELECT CAP_ID FROM AGENT_CAPABILITY_INDEX WHERE AGENT_ID = :aid AND CAPABILITY = :cap",
        {"aid": agent_id, "cap": capability},
    )
    if existing:
        execute(
            "UPDATE AGENT_CAPABILITY_INDEX SET CONFIDENCE = :conf, LAST_VERIFIED_AT = CURRENT_TIMESTAMP WHERE CAP_ID = :cid",
            {"conf": confidence, "cid": existing["cap_id"]},
        )
        return existing["cap_id"]
    return execute_insert_returning_id(
        """INSERT INTO AGENT_CAPABILITY_INDEX (CAP_ID, AGENT_ID, CAPABILITY, CONFIDENCE, LAST_VERIFIED_AT)
           VALUES (AI_NEW_ID(), :aid, :cap, :conf, CURRENT_TIMESTAMP) RETURNING CAP_ID INTO :ret_id""",
        {"aid": agent_id, "cap": capability, "conf": confidence},
    )


def discover_agents_by_capability(capability: str) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT a.AGENT_ID, a.AGENT_NAME, a.STATUS, c.CONFIDENCE, c.LAST_VERIFIED_AT
           FROM AGENT_CAPABILITY_INDEX c
           JOIN AGENT_REGISTRY a ON a.AGENT_ID = c.AGENT_ID
           WHERE c.CAPABILITY = :cap AND a.STATUS IN ('ACTIVE', 'POOL')
           ORDER BY c.CONFIDENCE DESC""",
        {"cap": capability},
    )
    return [_row_to_dict(r) for r in rows]


def get_agent_capabilities(agent_id: str) -> List[Dict[str, Any]]:
    rows = execute_query(
        "SELECT * FROM AGENT_CAPABILITY_INDEX WHERE AGENT_ID = :aid ORDER BY CONFIDENCE DESC",
        {"aid": agent_id},
    )
    return [_row_to_dict(r) for r in rows]


def match_skill_to_agents(skill_id: str) -> List[Dict[str, Any]]:
    from . import skill_api
    skill = skill_api.get_skill(skill_id)
    if not skill:
        return []
    skill_type = skill.get("skill_type", "")
    skill_runtime = skill.get("runtime", "")
    capabilities: List[str] = []
    if skill_type:
        capabilities.append(skill_type)
    if skill_runtime:
        capabilities.append(skill_runtime)

    results: List[Dict[str, Any]] = []
    for cap in capabilities:
        agents = discover_agents_by_capability(cap)
        for a in agents:
            a["matched_capability"] = cap
            results.append(a)
    seen = set()
    unique: List[Dict[str, Any]] = []
    for r in results:
        aid = r.get("agent_id")
        if aid not in seen:
            seen.add(aid)
            unique.append(r)
    return unique


def recommend_agents(task_description: str, limit: int = 5) -> List[Dict[str, Any]]:
    keywords = task_description.lower().split()
    results: List[Dict[str, Any]] = []
    seen = set()
    for kw in keywords:
        if len(kw) < 3:
            continue
        rows = execute_query(
            """SELECT DISTINCT a.AGENT_ID, a.AGENT_NAME, a.STATUS, c.CAPABILITY, c.CONFIDENCE
               FROM AGENT_CAPABILITY_INDEX c
               JOIN AGENT_REGISTRY a ON a.AGENT_ID = c.AGENT_ID
               WHERE UPPER(c.CAPABILITY) LIKE :kw AND a.STATUS IN ('ACTIVE', 'POOL')
               ORDER BY c.CONFIDENCE DESC
               FETCH FIRST :limit ROWS ONLY""",
            {"kw": f"%{kw.upper()}%", "limit": limit},
        )
        for r in rows:
            aid = r.get("agent_id")
            if aid not in seen:
                seen.add(aid)
                results.append(_row_to_dict(r))
                if len(results) >= limit:
                    return results
    return results


# ---------------------------------------------------------------------------
# D6: Event Dead Letter Queue
# ---------------------------------------------------------------------------

def _ensure_dead_letter_table() -> None:
    """EVENT_DEAD_LETTER is installed by the versioned database migration."""


def send_to_dead_letter(
    event_id: Optional[str],
    agent_id: Optional[str],
    event_type: str,
    payload: Any,
    reason: str,
) -> Optional[str]:
    """Route a failed event to the EVENT_DEAD_LETTER table.

    Returns the new DEAD_LETTER_ID, or None on failure.
    """
    _ensure_dead_letter_table()
    try:
        payload_str = payload if isinstance(payload, str) else json.dumps(payload)
        insert_sql = """
            INSERT INTO EVENT_DEAD_LETTER
                (DEAD_LETTER_ID, ORIGINAL_EVENT_ID, AGENT_ID, EVENT_TYPE,
                 EVENT_PAYLOAD, FAILURE_REASON, STATUS, FIRST_FAILED_AT)
            VALUES (AI_NEW_ID(), :orig, :aid, :etype,
                    :payload, :reason, 'PENDING', CURRENT_TIMESTAMP)
            RETURNING DEAD_LETTER_ID INTO :ret_id
        """
        return execute_insert_returning_id(insert_sql, {
            "orig": event_id, "aid": agent_id, "etype": event_type,
            "payload": payload_str, "reason": reason[:4000] if reason else None,
        })
    except Exception as e:
        logger.error("send_to_dead_letter failed: %s", e)
        return None


def retry_dead_letter(dead_letter_id: str) -> bool:
    """Attempt to resend a dead-lettered event.

    Returns True if the retry succeeded (event republished), False otherwise.
    On success the row STATUS is set to 'REPROCESSED'; on failure the row's
    RETRY_COUNT is incremented and LAST_RETRY_AT updated, and STATUS becomes
    'EXHAUSTED' once MAX_RETRIES is reached.
    """
    _ensure_dead_letter_table()
    try:
        row = execute_query_one(
            "SELECT * FROM EVENT_DEAD_LETTER WHERE DEAD_LETTER_ID = :dlid",
            {"dlid": dead_letter_id},
        )
    except Exception as e:
        logger.error("retry_dead_letter lookup failed: %s", e)
        return False
    if not row:
        return False

    event_type = row.get("event_type")
    payload = row.get("event_payload")
    agent_id = row.get("agent_id")
    retry_count = int(row.get("retry_count", 0) or 0)
    max_retries = int(row.get("max_retries", 5) or 5)

    # Parse payload back to dict (publish_event will re-serialize it).
    try:
        payload_dict = json.loads(payload) if payload else None
    except (json.JSONDecodeError, TypeError):
        payload_dict = payload

    # Republish — note: publish_event itself routes failures back here, so
    # we bypass the DLQ re-routing by catching publish_event exceptions
    # directly via execute_insert_returning_id to avoid infinite recursion.
    try:
        new_event_id = execute_insert_returning_id(
            """INSERT INTO EVENT_LOG (EVENT_ID, EVENT_TYPE, SOURCE_ID, SOURCE_TYPE, PAYLOAD)
               VALUES (AI_NEW_ID(), :etype, :sid, :stype, :payload)
               RETURNING EVENT_ID INTO :ret_id""",
            {
                "etype": event_type, "sid": agent_id, "stype": "AGENT",
                "payload": json.dumps(payload_dict) if payload_dict is not None else None,
            },
        )
        if new_event_id:
            execute(
                """UPDATE EVENT_DEAD_LETTER
                      SET STATUS = 'REPROCESSED',
                          RETRY_COUNT = :cnt,
                          LAST_RETRY_AT = CURRENT_TIMESTAMP
                    WHERE DEAD_LETTER_ID = :dlid""",
                {"cnt": retry_count + 1, "dlid": dead_letter_id},
            )
            logger.info("Dead letter %s reprocessed -> event %s",
                        dead_letter_id, new_event_id)
            return True
    except Exception as e:
        logger.warning("Dead letter %s retry failed: %s", dead_letter_id, e)
        new_status = "EXHAUSTED" if retry_count + 1 >= max_retries else "PENDING"
        try:
            execute(
                """UPDATE EVENT_DEAD_LETTER
                      SET RETRY_COUNT = :cnt,
                          LAST_RETRY_AT = CURRENT_TIMESTAMP,
                          STATUS = :status,
                          FAILURE_REASON = :reason
                    WHERE DEAD_LETTER_ID = :dlid""",
                {
                    "cnt": retry_count + 1,
                    "status": new_status,
                    "reason": f"Retry failed: {e}"[:4000],
                    "dlid": dead_letter_id,
                },
            )
        except Exception:
            pass
        return False
    return False


def list_dead_letters(status: str = "PENDING", limit: int = 50) -> List[Dict[str, Any]]:
    """List dead-letter entries filtered by status, newest first."""
    _ensure_dead_letter_table()
    try:
        rows = execute_query(
            """SELECT DEAD_LETTER_ID, ORIGINAL_EVENT_ID, AGENT_ID, EVENT_TYPE,
                      EVENT_PAYLOAD, FAILURE_REASON, RETRY_COUNT, MAX_RETRIES,
                      STATUS,
                      TO_CHAR(FIRST_FAILED_AT, 'YYYY-MM-DD HH24:MI:SS') AS FIRST_FAILED_AT,
                      TO_CHAR(LAST_RETRY_AT, 'YYYY-MM-DD HH24:MI:SS') AS LAST_RETRY_AT,
                      TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
                 FROM EVENT_DEAD_LETTER
                WHERE STATUS = :status
                ORDER BY FIRST_FAILED_AT DESC
                FETCH FIRST :lim ROWS ONLY""",
            {"status": status, "lim": limit},
        )
        return [_row_to_dict(r) for r in rows] if rows else []
    except Exception as e:
        logger.warning("list_dead_letters failed: %s", e)
        return []
