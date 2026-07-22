"""AI Agent Infra v4.0.1 - Enterprise Edition - Agent Communication Protocol

Inter-agent messaging for collaboration groups. Supports direct messages,
broadcast, threaded replies, priority levels, and attachment references.

Tables: COLLAB_MESSAGES
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert_returning_id,
    sanitize_row,
)

logger = logging.getLogger(__name__)

_JSON_COLUMNS = set()

_ALLOWED_UPDATE_FIELDS = frozenset({"subject", "body", "message_type", "priority", "status"})


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    return sanitize_row(row)


def send_message(
    group_id: str,
    sender_agent_id: str,
    body: str,
    receiver_agent_id: Optional[str] = None,
    subject: Optional[str] = None,
    message_type: str = "TEXT",
    priority: str = "NORMAL",
    parent_message_id: Optional[str] = None,
    attachment_entity_id: Optional[str] = None,
) -> str:
    if parent_message_id:
        parent = execute_query_one(
            "SELECT THREAD_ID FROM COLLAB_MESSAGES WHERE MESSAGE_ID = :mid",
            {"mid": parent_message_id},
        )
        thread_id = parent["thread_id"] if parent and parent.get("thread_id") else parent_message_id
    else:
        thread_id = None

    return execute_insert_returning_id(
        """INSERT INTO COLLAB_MESSAGES
           (MESSAGE_ID, GROUP_ID, SENDER_AGENT_ID, RECEIVER_AGENT_ID,
            PARENT_MESSAGE_ID, THREAD_ID, SUBJECT, BODY,
            MESSAGE_TYPE, PRIORITY, STATUS, ATTACHMENT_ENTITY_ID)
           VALUES (AI_NEW_ID(), :gid, :sender, :receiver,
                   :parent, :thread, :subject, :body,
                   :mtype, :priority, 'SENT', :attach)
           RETURNING MESSAGE_ID INTO :ret_id""",
        {
            "gid": group_id, "sender": sender_agent_id, "receiver": receiver_agent_id,
            "parent": parent_message_id, "thread": thread_id, "subject": subject,
            "body": body, "mtype": message_type, "priority": priority,
            "attach": attachment_entity_id,
        },
    )


def get_message(message_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one(
        "SELECT * FROM COLLAB_MESSAGES WHERE MESSAGE_ID = :mid",
        {"mid": message_id},
    )
    return _row_to_dict(row) if row else None


def get_messages(
    group_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    message_type: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    thread_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    clauses = []
    params: Dict[str, Any] = {"limit": limit, "offset": offset}

    if group_id:
        clauses.append("GROUP_ID = :gid")
        params["gid"] = group_id
    if agent_id:
        clauses.append("(SENDER_AGENT_ID = :aid OR RECEIVER_AGENT_ID = :aid OR RECEIVER_AGENT_ID IS NULL)")
        params["aid"] = agent_id
    if message_type:
        clauses.append("MESSAGE_TYPE = :mtype")
        params["mtype"] = message_type
    if priority:
        clauses.append("PRIORITY = :prio")
        params["prio"] = priority
    if status:
        clauses.append("STATUS = :stat")
        params["stat"] = status
    if thread_id:
        clauses.append("THREAD_ID = :tid")
        params["tid"] = thread_id

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = execute_query(
        f"""SELECT * FROM (
              SELECT m.*, ROW_NUMBER() OVER (ORDER BY CREATED_AT DESC) AS rn
              FROM COLLAB_MESSAGES m WHERE {where}
            ) WHERE rn > :offset AND rn <= :offset + :limit""",
        params,
    )
    return [_row_to_dict(r) for r in rows]


def get_conversation(message_id: str) -> List[Dict[str, Any]]:
    msg = get_message(message_id)
    if not msg:
        return []
    thread_id = msg.get("thread_id") or message_id
    rows = execute_query(
        """SELECT * FROM COLLAB_MESSAGES
           WHERE THREAD_ID = :tid OR MESSAGE_ID = :tid
           ORDER BY CREATED_AT""",
        {"tid": thread_id},
    )
    return [_row_to_dict(r) for r in rows]


def mark_read(message_id: str, agent_id: str) -> bool:
    affected = execute(
        """UPDATE COLLAB_MESSAGES
           SET READ_AT = CURRENT_TIMESTAMP, STATUS = 'READ'
           WHERE MESSAGE_ID = :mid
             AND (RECEIVER_AGENT_ID = :aid OR RECEIVER_AGENT_ID IS NULL)""",
        {"mid": message_id, "aid": agent_id},
    )
    return affected > 0


def mark_delivered(message_id: str) -> bool:
    affected = execute(
        "UPDATE COLLAB_MESSAGES SET STATUS = 'DELIVERED' WHERE MESSAGE_ID = :mid AND STATUS = 'SENT'",
        {"mid": message_id},
    )
    return affected > 0


def get_unread_count(agent_id: str, group_id: Optional[str] = None) -> int:
    clauses = [
        "(RECEIVER_AGENT_ID = :aid OR RECEIVER_AGENT_ID IS NULL)",
        "STATUS IN ('SENT', 'DELIVERED')",
    ]
    params: Dict[str, Any] = {"aid": agent_id}
    if group_id:
        clauses.append("GROUP_ID = :gid")
        params["gid"] = group_id

    row = execute_query_one(
        f"SELECT COUNT(*) AS CNT FROM COLLAB_MESSAGES WHERE {' AND '.join(clauses)}",
        params,
    )
    return row["cnt"] if row else 0


def reply_message(
    parent_id: str,
    sender_agent_id: str,
    body: str,
    attachment_entity_id: Optional[str] = None,
) -> str:
    parent = execute_query_one(
        "SELECT GROUP_ID, THREAD_ID FROM COLLAB_MESSAGES WHERE MESSAGE_ID = :mid",
        {"mid": parent_id},
    )
    if not parent:
        raise ValueError(f"Parent message not found: {parent_id}")

    thread_id = parent.get("thread_id") or parent_id
    return send_message(
        group_id=parent["group_id"],
        sender_agent_id=sender_agent_id,
        body=body,
        receiver_agent_id=None,
        message_type="RESPONSE",
        parent_message_id=parent_id,
        attachment_entity_id=attachment_entity_id,
    )


def broadcast_message(
    group_id: str,
    sender_agent_id: str,
    subject: str,
    body: str,
    priority: str = "NORMAL",
) -> str:
    return send_message(
        group_id=group_id,
        sender_agent_id=sender_agent_id,
        body=body,
        receiver_agent_id=None,
        subject=subject,
        message_type="NOTIFICATION",
        priority=priority,
    )


def delete_message(message_id: str, agent_id: str) -> bool:
    affected = execute(
        """UPDATE COLLAB_MESSAGES SET STATUS = 'DELETED'
           WHERE MESSAGE_ID = :mid AND SENDER_AGENT_ID = :aid""",
        {"mid": message_id, "aid": agent_id},
    )
    return affected > 0


def get_group_inbox(group_id: str, agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT * FROM (
              SELECT m.*, ROW_NUMBER() OVER (ORDER BY CREATED_AT DESC) AS rn
              FROM COLLAB_MESSAGES m
              WHERE GROUP_ID = :gid
                AND (RECEIVER_AGENT_ID = :aid OR RECEIVER_AGENT_ID IS NULL)
                AND STATUS != 'DELETED'
            ) WHERE rn <= :limit""",
        {"gid": group_id, "aid": agent_id, "limit": limit},
    )
    return [_row_to_dict(r) for r in rows]


def get_sent_messages(sender_agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT * FROM (
              SELECT m.*, ROW_NUMBER() OVER (ORDER BY CREATED_AT DESC) AS rn
              FROM COLLAB_MESSAGES m WHERE SENDER_AGENT_ID = :aid AND STATUS != 'DELETED'
            ) WHERE rn <= :limit""",
        {"aid": sender_agent_id, "limit": limit},
    )
    return [_row_to_dict(r) for r in rows]


def get_thread_messages(thread_id: str) -> List[Dict[str, Any]]:
    rows = execute_query(
        "SELECT * FROM COLLAB_MESSAGES WHERE THREAD_ID = :tid OR MESSAGE_ID = :tid ORDER BY CREATED_AT",
        {"tid": thread_id},
    )
    return [_row_to_dict(r) for r in rows]


def search_messages(
    query: str,
    group_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    clauses = ["(UPPER(SUBJECT) LIKE :q OR UPPER(BODY) LIKE :q)"]
    params: Dict[str, Any] = {"q": f"%{query.upper()}%"}

    if group_id:
        clauses.append("GROUP_ID = :gid")
        params["gid"] = group_id
    if agent_id:
        clauses.append("(SENDER_AGENT_ID = :aid OR RECEIVER_AGENT_ID = :aid)")
        params["aid"] = agent_id

    rows = execute_query(
        f"""SELECT * FROM (
              SELECT m.*, ROW_NUMBER() OVER (ORDER BY CREATED_AT DESC) AS rn
              FROM COLLAB_MESSAGES m WHERE {' AND '.join(clauses)}
            ) WHERE rn <= 50""",
        params,
    )
    return [_row_to_dict(r) for r in rows]


def get_message_stats(group_id: str) -> Dict[str, Any]:
    rows = execute_query(
        """SELECT MESSAGE_TYPE, PRIORITY, STATUS, COUNT(*) AS CNT
           FROM COLLAB_MESSAGES WHERE GROUP_ID = :gid
           GROUP BY MESSAGE_TYPE, PRIORITY, STATUS""",
        {"gid": group_id},
    )
    stats: Dict[str, Any] = {"by_type": {}, "by_priority": {}, "by_status": {}, "total": 0}
    for r in rows:
        mtype = r.get("message_type", "UNKNOWN")
        prio = r.get("priority", "UNKNOWN")
        stat = r.get("status", "UNKNOWN")
        cnt = r.get("cnt", 0)
        stats["by_type"][mtype] = stats["by_type"].get(mtype, 0) + cnt
        stats["by_priority"][prio] = stats["by_priority"].get(prio, 0) + cnt
        stats["by_status"][stat] = stats["by_status"].get(stat, 0) + cnt
        stats["total"] += cnt
    return stats
