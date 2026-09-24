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


# Conversational filler is not evidence of subject relevance. In particular,
# matching "in"/"one"/"explain" previously returned unrelated enterprise text.
_QUERY_STOP_WORDS = frozenset('a an the and or of to in on at for from with by '
    'is are was were be been being it its this that these those i me my we our '
    'you your they their what which who when where why how can could would should '
    'do does did please explain describe tell about one sentence sentences briefly'.split())


def _search_terms(query: str) -> list[str]:
    # Keep Chinese subjects intact: a shared fragment such as 公司 must not
    # make 甲骨文公司 match an unrelated company policy. Strip only anchored
    # conversational wrappers, never arbitrary characters inside the subject.
    terms = []
    for term in re.findall(r'[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}', query.lower()):
        if re.fullmatch(r'[\u4e00-\u9fff]+', term):
            previous = None
            while term != previous:
                previous = term
                term = re.sub(r'^(?:请问|请|帮我|给我|麻烦|我想了解|想了解|查询一下|查询|查一下|介绍一下|介绍|解释一下|解释|告诉我|了解一下|了解|关于)', '', term)
                term = re.sub(r'(?:是什么|有哪些功能|有什么功能|的相关信息|的基本情况|的信息|的情况|怎么样)$', '', term)
        if len(term) >= 2 and term not in _QUERY_STOP_WORDS:
            terms.append(term)
    return list(dict.fromkeys(terms))


def _matches_subject(item: dict[str, Any], terms: list[str]) -> bool:
    # Summary is candidate metadata, not the title/content sent to the model.
    # Require the actual authorized source to support every subject term.
    text = (str(item.get('title') or '') + '\n' + str(item.get('content') or '')).lower()
    return all(bool(re.search(r'(?<![a-z0-9_])' + re.escape(term) + r'(?![a-z0-9_])', text))
               if re.fullmatch(r'[a-z0-9_]+', term) else term in text for term in terms)


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
    terms = _search_terms(query)
    if query.strip() and (not terms or len(terms) > 24):
        return {"status": "NO_MATCH", "items": [], "retrieval_mode": "KEYWORD"}
    params: dict[str, Any] = {"actor": actor, "agent": agent, "lim": 100}
    predicates = ["e.ENTITY_TYPE='KNOWLEDGE'", "e.STATUS='ACTIVE'",
        "(e.EXPIRES_AT IS NULL OR e.EXPIRES_AT>CURRENT_TIMESTAMP)",
        knowledge_api.knowledge_access_predicate("e", ":actor"), knowledge_api.knowledge_access_predicate("e", ":agent")]
    if terms:
        predicates.append("(" + " AND ".join(f"(LOWER(e.TITLE) LIKE :q{i} ESCAPE '!' OR LOWER(e.SUMMARY) LIKE :q{i} ESCAPE '!' OR LOWER(e.CONTENT) LIKE :q{i} ESCAPE '!')" for i in range(len(terms))) + ")")
        params.update({f"q{i}": "%" + term.replace('!', '!!').replace('%', '!%').replace('_', '!_') + "%" for i, term in enumerate(terms)})
        relevance = " + ".join(
            f"CASE WHEN LOWER(e.TITLE) LIKE :q{i} ESCAPE '!' THEN 8 WHEN LOWER(e.SUMMARY) LIKE :q{i} ESCAPE '!' THEN 3 WHEN LOWER(e.CONTENT) LIKE :q{i} ESCAPE '!' THEN 1 ELSE 0 END"
            for i in range(len(terms))
        )
    else:
        # Empty-query inventory must use valid sortable SQL on every adapter.
        relevance = "e.UPDATED_AT"
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
        if terms and not _matches_subject(item, terms):
            continue
        items.append(item)
        if len(items) >= max(1, min(limit, 20)):
            break
    return {"status": "MATCHED" if items else "NO_MATCH", "items": items, "retrieval_mode": "KEYWORD"}
