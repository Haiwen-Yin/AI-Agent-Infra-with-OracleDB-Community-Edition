"""AI Agent Infra v4.0.0 - Enterprise Edition - Deployment Check API

Pre-deployment safety checks for AI Agents.
Agents MUST call check_deployment() before running any deploy scripts.
"""

import logging
from typing import Any, Dict, Optional

from .connection import execute_query

logger = logging.getLogger(__name__)


def check_deployment() -> Dict[str, Any]:
    """Check if the database already has an AI Agent Infra deployment.

    Agents MUST call this function BEFORE running any deploy scripts.
    If a deployment exists, the agent should NOT reinitialize the database.

    Returns:
        {
            "deployed": bool,
            "schema_version": str or None,
            "table_count": int,
            "edition": str or None,
            "agent_count": int,
            "user_count": int,
            "recommendation": str
        }
    """
    result = {
        "deployed": False,
        "schema_version": None,
        "table_count": 0,
        "edition": None,
        "agent_count": 0,
        "user_count": 0,
        "recommendation": "",
    }

    try:
        rows = execute_query(
            "SELECT COUNT(*) AS cnt FROM USER_TABLES WHERE TABLE_NAME != 'DBTOOLS$MCP_LOG'"
        )
        result["table_count"] = int(rows[0]["cnt"]) if rows else 0
    except Exception:
        result["table_count"] = 0

    if result["table_count"] == 0:
        result["deployed"] = False
        result["recommendation"] = (
            "No deployment detected. Safe to run full deployment:\n"
            "  sql user/pass@host:port/service @scripts/deploy/1_schema.sql\n"
            "  sql user/pass@host:port/service @scripts/deploy/2_api.sql\n"
            "  sql user/pass@host:port/service @scripts/deploy/3_jobs.sql\n"
            "  sql user/pass@host:port/service @scripts/deploy/4_harness_templates.sql"
        )
        return result

    try:
        rows = execute_query(
            "SELECT CONFIG_VALUE FROM SYSTEM_CONFIG WHERE CONFIG_KEY = 'schema_version'"
        )
        if rows:
            result["schema_version"] = rows[0]["config_value"]
            result["deployed"] = True
    except Exception:
        pass

    try:
        rows = execute_query(
            "SELECT CONFIG_VALUE FROM SYSTEM_CONFIG WHERE CONFIG_KEY = 'edition'"
        )
        if rows:
            result["edition"] = rows[0]["config_value"]
    except Exception:
        pass

    try:
        rows = execute_query("SELECT COUNT(*) AS cnt FROM AGENT_REGISTRY")
        result["agent_count"] = int(rows[0]["cnt"]) if rows else 0
    except Exception:
        pass

    try:
        rows = execute_query("SELECT COUNT(*) AS cnt FROM SYSTEM_USERS")
        result["user_count"] = int(rows[0]["cnt"]) if rows else 0
    except Exception:
        pass

    if result["deployed"]:
        result["recommendation"] = (
            f"EXISTING DEPLOYMENT DETECTED (v{result['schema_version']}, "
            f"{result['table_count']} tables, {result['agent_count']} agents, "
            f"{result['user_count']} users). "
            f"DO NOT re-run deploy scripts — this will DESTROY all existing data. "
            f"If you need to register this Skill, use skill_api.register_skill() only. "
            f"If you need to upgrade, use incremental upgrade scripts. "
            f"If you must reinitialize, a human admin must manually drop all tables first."
        )
    else:
        result["recommendation"] = (
            f"Database has {result['table_count']} tables but no schema_version marker. "
            f"This may be a partial or corrupted deployment. "
            f"Consult a human admin before proceeding."
        )

    return result
