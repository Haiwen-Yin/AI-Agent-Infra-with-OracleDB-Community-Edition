"""Database-backed opaque cursor contract for v4.4.1 inventories.

Cursor records bind the authenticated principal, resource, canonical filters,
sort order and page size.  They are intentionally short-lived and do not
contain a SQL fragment or an authorization decision supplied by the client.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from . import connection


class CursorError(ValueError):
    """A cursor cannot be used for the requested inventory."""


def _id() -> str:
    return "CUR_" + secrets.token_urlsafe(24)


def _canonical(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _expiry_sql() -> str:
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"}:
        return "CURRENT_TIMESTAMP + INTERVAL '15 minutes'"
    return "CURRENT_TIMESTAMP + INTERVAL '15' MINUTE"


def normalize_page_size(value: int) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = 20
    if size not in {20, 50, 100}:
        raise CursorError("page size must be 20, 50, or 100")
    return size


def resolve(principal_id: str, resource_key: str, filters: Dict[str, Any], sort_key: str,
            page_size: int, cursor_id: str = "") -> Dict[str, Any]:
    """Resolve a client cursor to a trusted keyset position."""
    size = normalize_page_size(page_size)
    digest = _digest(filters)
    if not cursor_id:
        return {"cursor_id": "", "position": {}, "page_size": size, "filter_digest": digest}
    row = connection.execute_query_one(
        "SELECT CURSOR_ID,POSITION_KEY,PAGE_SIZE FROM CX_API_CURSORS WHERE CURSOR_ID=:cursor_id "
        "AND PRINCIPAL_ID=:principal_id AND RESOURCE_KEY=:resource_key AND FILTER_DIGEST=:filter_digest "
        "AND SORT_KEY=:sort_key AND EXPIRES_AT>CURRENT_TIMESTAMP",
        {"cursor_id": cursor_id, "principal_id": principal_id, "resource_key": resource_key,
         "filter_digest": digest, "sort_key": sort_key},
    )
    if not row:
        raise CursorError("cursor is expired or outside the authorized inventory")
    if int(row.get("page_size") or 0) != size:
        raise CursorError("cursor page size does not match the requested page size")
    try:
        position = json.loads(str(row.get("position_key") or "{}"))
    except (TypeError, ValueError):
        raise CursorError("cursor position is invalid") from None
    if not isinstance(position, dict):
        raise CursorError("cursor position is invalid")
    return {"cursor_id": cursor_id, "position": position, "page_size": size, "filter_digest": digest}


def issue(principal_id: str, resource_key: str, filter_digest: str, sort_key: str,
          page_size: int, position: Optional[Dict[str, Any]]) -> str:
    """Persist the next opaque cursor only when another page exists."""
    if not position:
        return ""
    cursor_id = _id()
    connection.execute(
        "INSERT INTO CX_API_CURSORS(CURSOR_ID,PRINCIPAL_ID,RESOURCE_KEY,FILTER_DIGEST,SORT_KEY,PAGE_SIZE,POSITION_KEY,EXPIRES_AT) "
        "VALUES (:cursor_id,:principal_id,:resource_key,:filter_digest,:sort_key,:page_size,:position_json," + _expiry_sql() + ")",
        {"cursor_id": cursor_id, "principal_id": principal_id, "resource_key": resource_key,
         "filter_digest": filter_digest, "sort_key": sort_key, "page_size": page_size,
         "position_json": _canonical(position)},
    )
    return cursor_id


def page(items: list[Dict[str, Any]], context: Dict[str, Any], position_for: Any) -> Dict[str, Any]:
    """Trim a limit+1 query and issue a follow-up cursor from its last row."""
    size = int(context["page_size"])
    has_more = len(items) > size
    visible = items[:size]
    next_cursor = issue(
        str(context["principal_id"]), str(context["resource_key"]),
        str(context["filter_digest"]), str(context["sort_key"]), size,
        position_for(visible[-1]) if has_more and visible else None,
    )
    return {"items": visible, "count": len(visible), "page_size": size,
            "next_cursor": next_cursor or None, "has_more": has_more}
