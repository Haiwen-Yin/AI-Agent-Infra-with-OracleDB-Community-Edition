"""AI Agent Infra v4.0.0 - Enterprise Edition - Skill Token API"""

import secrets
import time
from typing import Dict, Optional

from .connection import execute, execute_query_one, execute_insert_returning_id
from .config import get_config
from .skill_storage import read_resource_content


def request_skill_access(agent_id: str, session_id: str, skill_id: str) -> Optional[Dict]:
    agent = execute_query_one(
        "SELECT STATUS FROM AGENT_REGISTRY WHERE AGENT_ID = :aid",
        {"aid": agent_id},
    )
    if agent is None or agent.get("status") != "ACTIVE":
        return None

    skill = execute_query_one(
        "SELECT SKILL_STATUS, RESOURCE_URI FROM SKILL_META WHERE ENTITY_ID = :sid",
        {"sid": skill_id},
    )
    if skill is None or skill.get("skill_status") != "ACTIVE":
        return None

    resource_uri = skill.get("resource_uri")
    if not resource_uri:
        return None

    ttl_min = get_config().enterprise.skill_token_ttl_min
    expires_at = time.time() + ttl_min * 60

    token_sql = """
        INSERT INTO SKILL_ACCESS_TOKEN (TOKEN_ID, SKILL_ID, AGENT_ID, SESSION_ID, EXPIRES_AT, IS_CONSUMED)
        VALUES ('TKN_' || RAWTOHEX(SYS_GUID()), :skill_id, :agent_id, :session_id,
                SYSTIMESTAMP + NUMTODSINTERVAL(:ttl_sec, 'SECOND'),
                'N')
        RETURNING TOKEN_ID INTO :ret_id
    """
    token_id = execute_insert_returning_id(token_sql, {
        "skill_id": skill_id,
        "agent_id": agent_id,
        "session_id": session_id,
        "ttl_sec": ttl_min * 60,
    })

    return {
        "token_id": token_id,
        "skill_id": skill_id,
        "resource_uri": resource_uri,
        "expires_at": expires_at,
    }


def consume_skill_token(token_id: str) -> Optional[Dict]:
    row = execute_query_one(
        """SELECT TOKEN_ID, SKILL_ID, AGENT_ID
           FROM SKILL_ACCESS_TOKEN
           WHERE TOKEN_ID = :tid AND IS_CONSUMED = 'N' AND EXPIRES_AT > SYSTIMESTAMP""",
        {"tid": token_id},
    )
    if row is None:
        return None

    download_token = secrets.token_hex(32)
    ttl_sec = get_config().enterprise.presigned_url_ttl_sec
    download_expires = time.time() + ttl_sec

    execute(
        """UPDATE SKILL_ACCESS_TOKEN
           SET IS_CONSUMED = 'Y',
               CONSUMED_AT = SYSTIMESTAMP,
               DOWNLOAD_TOKEN = :dl_token,
               DOWNLOAD_EXPIRES_AT = SYSTIMESTAMP + NUMTODSINTERVAL(:dl_ttl, 'SECOND')
           WHERE TOKEN_ID = :tid""",
        {"tid": token_id, "dl_token": download_token, "dl_ttl": ttl_sec},
    )

    download_url = f"/api/skill/dl/{download_token}"

    return {
        "token_id": token_id,
        "skill_id": row["skill_id"],
        "download_url": download_url,
        "download_expires_at": download_expires,
        "consumed": True,
    }


def verify_download_token(download_token: str) -> Optional[Dict]:
    row = execute_query_one(
        """SELECT TOKEN_ID, SKILL_ID, AGENT_ID, DOWNLOAD_EXPIRES_AT
           FROM SKILL_ACCESS_TOKEN
           WHERE DOWNLOAD_TOKEN = :dl_token 
             AND DOWNLOAD_EXPIRES_AT > SYSTIMESTAMP""",
        {"dl_token": download_token},
    )
    if row is None:
        return None

    return {
        "token_id": row["token_id"],
        "skill_id": row["skill_id"],
        "agent_id": row["agent_id"],
    }


def get_skill_resource_for_download(download_token: str) -> Optional[Dict]:
    token_info = verify_download_token(download_token)
    if token_info is None:
        return None

    skill_id = token_info["skill_id"]
    content = read_resource_content(skill_id)
    if content is None:
        return None

    execute(
        """UPDATE SKILL_ACCESS_TOKEN
           SET DOWNLOAD_TOKEN = NULL,
               DOWNLOAD_EXPIRES_AT = NULL
           WHERE DOWNLOAD_TOKEN = :dl_token""",
        {"dl_token": download_token},
    )

    from .skill_api import get_skill
    skill = get_skill(skill_id)
    skill_name = skill.get("skill_name", "skill") if skill else "skill"
    skill_version = skill.get("skill_version", "1.0.0") if skill else "1.0.0"

    return {
        "content": content,
        "mime_type": "application/zip",
        "filename": f"{skill_name}-{skill_version}.zip",
        "skill_id": skill_id,
    }


def cleanup_expired_tokens() -> int:
    result = execute(
        """DELETE FROM SKILL_ACCESS_TOKEN
           WHERE (IS_CONSUMED = 'Y' OR EXPIRES_AT < SYSTIMESTAMP)
             AND CREATED_AT < SYSTIMESTAMP - INTERVAL '7' DAY""",
    )
    return result
