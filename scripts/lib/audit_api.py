"""AI Agent Infra v3.10.2 - Community Edition - Audit API (stub)

Community Edition does not include full audit functionality.
Provides minimal stubs to prevent import errors.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_audit_events(limit: int = 100) -> List[Dict[str, Any]]:
    return []


def get_audit_stats() -> Dict[str, Any]:
    return {"total": 0, "by_type": {}, "by_action": {}}
