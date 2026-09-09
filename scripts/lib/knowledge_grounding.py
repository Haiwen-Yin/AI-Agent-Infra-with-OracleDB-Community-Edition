"""Shared user/Agent intersection retrieval with fresh citation authorization."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from . import connection, content_security, identity_api, knowledge_api, agent_registration


class GroundingError(ValueError):
    pass


def require_reader(actor: str, agent: str) -> None:
    if not actor or not agent:
        raise PermissionError("Authenticated user and Agent are required")
    for principal in {actor, agent}:
        if identity_api.effective_access(principal, "knowledge.read").get("decision") != "ALLOW":
            raise PermissionError("Knowledge access is unavailable")
        row = connection.execute_query_one("SELECT STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id", {"id": principal})
        if row:
            if str(next((v for k, v in row.items() if k.lower() == "status"), "")).upper() != "ACTIVE":
                raise PermissionError("Knowledge principal is inactive")
        elif principal == agent:
            # Pool Agents may expose a registry alias instead of a principal id.
            # Their admission is authoritative in the registration inventory.
            registration = agent_registration.get_registration(principal)
            if not registration or str(registration.get("status") or "").upper() != "ACTIVE":
                raise PermissionError("Knowledge Agent is inactive")
        else:
            raise PermissionError("Knowledge principal is inactive")


def _valid(item: dict[str, Any]) -> bool:
    if str(item.get("status", "")).upper() != "ACTIVE":
        return False
    expiry = item.get("expires_at")
    if not expiry:
        return True
    try:
        instant = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
        return instant.replace(tzinfo=instant.tzinfo or timezone.utc) > datetime.now(timezone.utc)
    except ValueError:
        return False


def citation(actor: str, agent: str, entity_id: str, expected_digest: str = "") -> dict[str, Any]:
    require_reader(actor, agent)
    item = knowledge_api.get_knowledge(entity_id, principal_id=actor)
    delegated = knowledge_api.get_knowledge(entity_id, principal_id=agent)
    if not item or not delegated or not _valid(item) or not _valid(delegated):
        raise PermissionError("Knowledge is unavailable")
    content = str(item.get("content") or "")
    digest = hashlib.sha256(json.dumps({"content": content, "title": item.get("title"),
        "updated_at": str(item.get("updated_at") or "")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if expected_digest and digest != expected_digest:
        raise GroundingError("Knowledge version changed")
    content_security.enforce(content, "KNOWLEDGE")
    return {"entity_id": str(entity_id), "title": str(item.get("title") or ""),
            "content": content, "digest": digest, "updated_at": str(item.get("updated_at") or ""),
            "domain": str(item.get("domain") or ""), "visibility": str(item.get("visibility") or "")}


def search(actor: str, agent: str, query: str, *, limit: int = 8, entity_ids: list[str] | None = None) -> dict[str, Any]:
    require_reader(actor, agent)
    if not isinstance(query, str) or len(query) > 2000:
        raise GroundingError("Knowledge query is invalid")
    if entity_ids is not None and (not isinstance(entity_ids, list) or len(entity_ids) > 50 or any(not isinstance(x, str) for x in entity_ids)):
        raise GroundingError("Knowledge source filter is invalid")
    # Every candidate is SQL-filtered by BOTH principals. Global read.all
    # cannot turn a delegated model request into unrestricted retrieval.
    terms = re.findall(r"[a-z0-9_]{2,40}|[\u4e00-\u9fff]{2,40}", query.lower())[:8]
    for run in re.findall(r"[\u4e00-\u9fff]{3,40}", query):
        terms.extend(run[i:i + 2] for i in range(len(run) - 1))
    terms = list(dict.fromkeys(terms))[:24]
    params: dict[str, Any] = {"actor": actor, "agent": agent, "lim": 100}
    predicates = ["e.ENTITY_TYPE='KNOWLEDGE'", "e.STATUS='ACTIVE'",
        "(e.EXPIRES_AT IS NULL OR e.EXPIRES_AT>CURRENT_TIMESTAMP)",
        knowledge_api.knowledge_access_predicate("e", ":actor"), knowledge_api.knowledge_access_predicate("e", ":agent")]
    if terms:
        predicates.append("(" + " OR ".join(f"(LOWER(e.TITLE) LIKE :q{i} OR LOWER(e.SUMMARY) LIKE :q{i} OR LOWER(e.CONTENT) LIKE :q{i})" for i in range(len(terms))) + ")")
        params.update({f"q{i}": "%" + term.replace("%", "").replace("_", "") + "%" for i, term in enumerate(terms)})
        relevance = " + ".join(
            f"CASE WHEN LOWER(e.TITLE) LIKE :q{i} THEN 8 WHEN LOWER(e.SUMMARY) LIKE :q{i} THEN 3 WHEN LOWER(e.CONTENT) LIKE :q{i} THEN 1 ELSE 0 END"
            for i in range(len(terms))
        )
    else:
        relevance = "0"
    if entity_ids is not None:
        if not entity_ids:
            return {"status": "NO_MATCH", "items": [], "retrieval_mode": "KEYWORD"}
        predicates.append("e.ENTITY_ID IN (" + ",".join(f":id{i}" for i in range(len(entity_ids))) + ")")
        params.update({f"id{i}": key for i, key in enumerate(entity_ids)})
    suffix = " LIMIT :lim" if str(connection.DATABASE_DIALECT).lower() in {"pg", "postgresql"} else " FETCH FIRST :lim ROWS ONLY"
    rows = connection.execute_query("SELECT e.ENTITY_ID FROM ENTITIES e WHERE " + " AND ".join(predicates) + " ORDER BY (" + relevance + ") DESC, e.UPDATED_AT DESC" + suffix, params)
    items = []
    for row in rows:
        entity_id = str(next(v for k, v in row.items() if k.lower() == "entity_id"))
        try:
            item = citation(actor, agent, entity_id)
        except PermissionError:
            continue
        items.append(item)
        if len(items) >= max(1, min(limit, 20)):
            break
    return {"status": "MATCHED" if items else "NO_MATCH", "items": items, "retrieval_mode": "KEYWORD"}
