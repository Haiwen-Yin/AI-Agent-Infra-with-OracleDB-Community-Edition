"""AI Agent Infra v4.4.11 - Community Edition - Knowledge API

Knowledge CRUD, graph edges, spaced-review, and tagging.
Operates on ENTITIES (ENTITY_TYPE='KNOWLEDGE') + KNOWLEDGE_META + ENTITY_EDGES.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from . import connection
from .connection import (
    DATABASE_DIALECT, execute, execute_query, execute_query_one,
    execute_insert_returning_id,
)
from . import cursor_pagination, identity_api

logger = logging.getLogger(__name__)


def _json_value(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False, separators=(",", ":"))


def get_agent_knowledge_context(agent_id: str) -> Dict[str, Any]:
    """Resolve the current relational and graph context for an Agent.

    The database is authoritative: the Agent is mapped to its active Human
    owner, the owner's primary organization is expanded through the closure,
    and both governed responsible groups and legacy execution groups are
    reported. This is a read-only snapshot used when knowledge is produced
    and when the graph projection is rendered.
    """
    agent = str(agent_id or "").strip()
    if not agent:
        raise ValueError("agent_id is required")
    owner = execute_query_one(
        "SELECT PRINCIPAL_ID, RESPONSIBLE_GROUP_ID FROM CX_AGENT_RELATIONSHIPS "
        "WHERE AGENT_ID=:agent_id AND RELATIONSHIP_ROLE='PRIMARY_OWNER' AND STATUS='ACTIVE'",
        {"agent_id": agent},
    ) or {}
    principal_id = str(owner.get("principal_id") or "")
    org_rows = execute_query(
        "SELECT o.ORGANIZATION_ID, o.ORGANIZATION_NAME, o.PARENT_ID, c.DEPTH "
        "FROM CX_ORGANIZATION_MEMBERS m "
        "JOIN CX_ORGANIZATION_CLOSURE c ON c.DESCENDANT_ID=m.ORGANIZATION_ID "
        "JOIN CX_ORGANIZATIONS o ON o.ORGANIZATION_ID=c.ANCESTOR_ID "
        "WHERE m.PRINCIPAL_ID=:principal_id AND m.STATUS='ACTIVE' "
        "AND m.VALID_FROM<=CURRENT_TIMESTAMP AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP) "
        "ORDER BY c.DEPTH DESC, o.ORGANIZATION_ID",
        {"principal_id": principal_id},
    ) if principal_id else []
    organization_chain = [
        {"organization_id": r.get("organization_id"), "organization_name": r.get("organization_name"),
         "parent_id": r.get("parent_id"), "depth": int(r.get("depth") or 0)}
        for r in org_rows
    ]
    org_id = organization_chain[-1]["organization_id"] if organization_chain else None
    responsible = execute_query(
        "SELECT g.GROUP_ID, g.GROUP_NAME, g.SECURITY_DOMAIN_ID, m.MEMBER_ROLE "
        "FROM CX_RESPONSIBLE_GROUPS g JOIN CX_RESPONSIBLE_GROUP_MEMBERS m ON m.GROUP_ID=g.GROUP_ID "
        "WHERE m.PRINCIPAL_ID=:principal_id AND m.STATUS='ACTIVE' AND g.STATUS='ACTIVE' "
        "ORDER BY g.GROUP_NAME",
        {"principal_id": principal_id},
    ) if principal_id else []
    relation_group = str(owner.get("responsible_group_id") or "")
    if relation_group and not any(str(r.get("group_id")) == relation_group for r in responsible):
        row = execute_query_one(
            "SELECT GROUP_ID, GROUP_NAME, SECURITY_DOMAIN_ID, 'AGENT_RELATION' AS MEMBER_ROLE "
            "FROM CX_RESPONSIBLE_GROUPS WHERE GROUP_ID=:group_id AND STATUS='ACTIVE'",
            {"group_id": relation_group},
        )
        if row:
            responsible.append(row)
    execution = execute_query(
        "SELECT g.GROUP_ID, g.GROUP_NAME, g.GROUP_TYPE, g.SHARING_POLICY, m.ROLE "
        "FROM COLLAB_GROUPS g JOIN COLLAB_GROUP_MEMBERS m ON m.GROUP_ID=g.GROUP_ID "
        "WHERE m.AGENT_ID=:agent_id AND m.STATUS='ACTIVE' AND g.STATUS='ACTIVE' "
        "ORDER BY g.GROUP_NAME",
        {"agent_id": agent},
    )
    return {
        "agent_id": agent, "principal_id": principal_id, "organization_id": org_id,
        "organization_chain": organization_chain,
        "responsible_groups": [{str(k).lower(): v for k, v in dict(r).items()} for r in responsible],
        "execution_groups": [{str(k).lower(): v for k, v in dict(r).items()} for r in execution],
    }


def get_knowledge_context(entity_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one(
        "SELECT CONTEXT_ID, ENTITY_ID, AGENT_ID, PRINCIPAL_ID, ORGANIZATION_ID, "
        "ORGANIZATION_CHAIN_JSON, RESPONSIBLE_GROUPS_JSON, EXECUTION_GROUPS_JSON, "
        "SHARING_SCOPE, GRAPH_SNAPSHOT_DIGEST FROM CX_KNOWLEDGE_CONTEXTS WHERE ENTITY_ID=:entity_id",
        {"entity_id": entity_id},
    )
    if not row:
        return None
    result = {str(k).lower(): v for k, v in dict(row).items()}
    for key in ("organization_chain_json", "responsible_groups_json", "execution_groups_json"):
        raw = result.pop(key, None)
        try:
            result[key.removesuffix("_json")] = json.loads(raw or "[]")
        except (TypeError, ValueError):
            result[key.removesuffix("_json")] = []
    return result


def capture_agent_knowledge_context(entity_id: str, agent_id: str, *, sharing_scope: str = "ORGANIZATION_SUBTREE",
                                    organization_id: Optional[str] = None, hierarchy_depth: Optional[int] = None,
                                    reason: str = "Agent knowledge creation",
                                    context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    entity_id = str(entity_id)
    context = context or get_agent_knowledge_context(agent_id)
    selected_org = organization_id or context.get("organization_id")
    scope = str(sharing_scope or "ORGANIZATION_SUBTREE").upper()
    if scope not in {"PUBLIC_COMPANY", "ORGANIZATION_SUBTREE", "ORGANIZATION_LEVEL", "PRINCIPAL_PRIVATE"}:
        raise ValueError("invalid knowledge sharing scope")
    if scope in {"ORGANIZATION_SUBTREE", "ORGANIZATION_LEVEL"} and not selected_org:
        raise ValueError("Agent has no active organization for organization-scoped knowledge")
    if scope == "ORGANIZATION_LEVEL" and (hierarchy_depth is None or int(hierarchy_depth) < 0):
        raise ValueError("organization level requires a non-negative hierarchy depth")
    digest = __import__("hashlib").sha256(_json_value({"agent": context, "scope": scope, "org": selected_org}).encode()).hexdigest()
    execute(
        "INSERT INTO CX_KNOWLEDGE_CONTEXTS (CONTEXT_ID,ENTITY_ID,AGENT_ID,PRINCIPAL_ID,ORGANIZATION_ID,"
        "ORGANIZATION_CHAIN_JSON,RESPONSIBLE_GROUPS_JSON,EXECUTION_GROUPS_JSON,SHARING_SCOPE,GRAPH_SNAPSHOT_DIGEST,REASON) "
        "VALUES (:context_id,:entity_id,:agent_id,:principal_id,:organization_id,:organization_chain,:responsible,:execution,:scope,:digest,:reason)",
        {"context_id": "KCTX_" + uuid.uuid4().hex, "entity_id": entity_id, "agent_id": context["agent_id"],
         "principal_id": context.get("principal_id") or None, "organization_id": selected_org,
         "organization_chain": _json_value(context["organization_chain"]),
         "responsible": _json_value(context["responsible_groups"]), "execution": _json_value(context["execution_groups"]),
         "scope": scope, "digest": digest, "reason": reason[:2000]},
    )
    if scope == "PRINCIPAL_PRIVATE":
        # Agent-private knowledge belongs to the producing Agent identity. The
        # Human owner remains provenance/context, not an implicit reader.
        target_principal = agent_id
        set_access_policy(entity_id, scope, target_principal, principal_id=target_principal, reason=reason)
    else:
        set_access_policy(entity_id, scope, context.get("principal_id") or agent_id,
                          organization_id=selected_org, hierarchy_depth=hierarchy_depth, reason=reason)
    return {"entity_id": entity_id, "sharing_scope": scope, "organization_id": selected_org,
            "organization_chain": context["organization_chain"], "responsible_groups": context["responsible_groups"],
            "execution_groups": context["execution_groups"], "graph_snapshot_digest": digest}

def set_access_policy(entity_id: str, scope_type: str, actor_id: str, *, organization_id: Optional[str] = None,
                      principal_id: Optional[str] = None, hierarchy_depth: Optional[int] = None,
                      reason: str = "policy change") -> Dict[str, Any]:
    entity_id = str(entity_id)
    allowed = {"PUBLIC_COMPANY", "ORGANIZATION_SUBTREE", "ORGANIZATION_LEVEL", "PRINCIPAL_PRIVATE"}
    if scope_type not in allowed or not reason.strip():
        raise ValueError("invalid knowledge access policy")
    if scope_type == "ORGANIZATION_LEVEL" and (not organization_id or hierarchy_depth is None or hierarchy_depth < 0):
        raise ValueError("organization level requires organization and non-negative depth")
    if scope_type == "ORGANIZATION_SUBTREE" and not organization_id:
        raise ValueError("organization subtree requires organization")
    if scope_type == "PRINCIPAL_PRIVATE" and not principal_id:
        raise ValueError("private policy requires principal")
    execute("UPDATE CX_KNOWLEDGE_ACCESS_POLICIES SET STATUS='RETIRED', UPDATED_AT=CURRENT_TIMESTAMP WHERE ENTITY_ID=:eid AND STATUS='ACTIVE'", {"eid": entity_id})
    policy_id = str(uuid.uuid4())
    execute("INSERT INTO CX_KNOWLEDGE_ACCESS_POLICIES (POLICY_ID,ENTITY_ID,SCOPE_TYPE,ORGANIZATION_ID,PRINCIPAL_ID,HIERARCHY_DEPTH,REASON,CREATED_BY) VALUES (:pid,:eid,:scope,:org,:principal,:depth,:reason,:actor)",
            {"pid": policy_id, "eid": entity_id, "scope": scope_type, "org": organization_id, "principal": principal_id, "depth": hierarchy_depth, "reason": reason[:2000], "actor": actor_id})
    return {"policy_id": policy_id, "entity_id": entity_id, "scope_type": scope_type, "organization_id": organization_id, "principal_id": principal_id, "hierarchy_depth": hierarchy_depth}

def get_access_policy(entity_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one("SELECT POLICY_ID,ENTITY_ID,SCOPE_TYPE,ORGANIZATION_ID,PRINCIPAL_ID,HIERARCHY_DEPTH,STATUS,REASON FROM CX_KNOWLEDGE_ACCESS_POLICIES WHERE ENTITY_ID=:eid AND STATUS='ACTIVE'", {"eid": entity_id})
    return {str(key).lower(): value for key, value in dict(row).items()} if row else None

def list_organization_policies(organization_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    entity_join = "CAST(e.ENTITY_ID AS VARCHAR(128))=kap.ENTITY_ID" if DATABASE_DIALECT == "postgresql" else "e.ENTITY_ID=kap.ENTITY_ID"
    rows = execute_query(
        "SELECT kap.POLICY_ID,kap.ENTITY_ID,kap.SCOPE_TYPE,kap.HIERARCHY_DEPTH,kap.STATUS,"
        "e.TITLE,e.DOMAIN FROM CX_KNOWLEDGE_ACCESS_POLICIES kap "
        "JOIN (SELECT en.ENTITY_ID,en.TITLE,km.DOMAIN FROM ENTITIES en JOIN KNOWLEDGE_META km "
        "ON km.ENTITY_ID=en.ENTITY_ID AND km.ENTITY_TYPE='KNOWLEDGE' WHERE en.ENTITY_TYPE='KNOWLEDGE') e "
        f"ON {entity_join} WHERE kap.ORGANIZATION_ID=:org AND kap.STATUS='ACTIVE' "
        "AND kap.VALID_FROM<=CURRENT_TIMESTAMP AND (kap.VALID_UNTIL IS NULL OR kap.VALID_UNTIL>CURRENT_TIMESTAMP) "
        "ORDER BY e.TITLE FETCH FIRST :lim ROWS ONLY",
        {"org": organization_id, "lim": max(1, min(limit, 500))},
    )
    return [{str(key).lower(): value for key, value in dict(row).items()} for row in rows]


def knowledge_access_predicate(entity_alias: str = "e", principal_expr: str = ":principal_id") -> str:
    """Database-authoritative visibility predicate; unknown policies fail closed.

    Legacy rows without a policy retain PUBLIC/SHARED or owner-private behavior
    so the v4.4.10 baseline can be adopted without rewriting existing content.
    Organization membership and closure are evaluated at read time.
    """
    entity_id = f"CAST({entity_alias}.ENTITY_ID AS VARCHAR(128))" if DATABASE_DIALECT == "postgresql" else f"{entity_alias}.ENTITY_ID"
    return f"""(/* SCOPE_CLAUSE: organization-aware knowledge policy */
      EXISTS (SELECT 1 FROM CX_KNOWLEDGE_ACCESS_POLICIES kap
       WHERE kap.ENTITY_ID={entity_id} AND kap.STATUS='ACTIVE'
         AND kap.VALID_FROM <= CURRENT_TIMESTAMP AND (kap.VALID_UNTIL IS NULL OR kap.VALID_UNTIL > CURRENT_TIMESTAMP)
         AND (kap.SCOPE_TYPE='PUBLIC_COMPANY'
           OR (kap.SCOPE_TYPE='PRINCIPAL_PRIVATE' AND kap.PRINCIPAL_ID={principal_expr})
           OR (kap.SCOPE_TYPE IN ('ORGANIZATION_SUBTREE','ORGANIZATION_LEVEL') AND EXISTS (
             SELECT 1 FROM CX_ORGANIZATION_MEMBERS kmem
             JOIN CX_ORGANIZATION_CLOSURE kcl ON kcl.DESCENDANT_ID=kmem.ORGANIZATION_ID
             WHERE kmem.PRINCIPAL_ID={principal_expr} AND kmem.STATUS='ACTIVE'
               AND kmem.VALID_FROM <= CURRENT_TIMESTAMP AND (kmem.VALID_UNTIL IS NULL OR kmem.VALID_UNTIL > CURRENT_TIMESTAMP)
               AND kcl.ANCESTOR_ID=kap.ORGANIZATION_ID
               AND (kap.SCOPE_TYPE='ORGANIZATION_SUBTREE' OR kcl.DEPTH <= kap.HIERARCHY_DEPTH))))
      )
      OR (NOT EXISTS (SELECT 1 FROM CX_KNOWLEDGE_ACCESS_POLICIES kp0 WHERE kp0.ENTITY_ID={entity_id})
          AND ({entity_alias}.VISIBILITY IN ('PUBLIC','SHARED') OR {entity_alias}.OWNED_BY_AGENT={principal_expr}))
    )"""


def create_knowledge(
    title: str,
    content: str,
    domain: Optional[str] = None,
    topic: Optional[str] = None,
    difficulty: str = "INTERMEDIATE",
    category: Optional[str] = None,
    importance: int = 5,
    summary: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "PRIVATE",
    workspace_id: Optional[str] = None,
    sharing_scope: Optional[str] = None,
    organization_id: Optional[str] = None,
    hierarchy_depth: Optional[int] = None,
    creation_reason: str = "Agent knowledge creation",
) -> str:
    # Resolve and validate the Agent's organization context before any row is
    # written. This keeps organization-scoped creation fail-closed without
    # leaving an entity/meta orphan when the Agent has no active owner chain.
    agent_context = None
    if owned_by_agent:
        requested_scope = sharing_scope or (
            "PRINCIPAL_PRIVATE" if str(visibility).upper() == "PRIVATE" else "ORGANIZATION_SUBTREE"
        )
        agent_context = get_agent_knowledge_context(owned_by_agent)
        normalized_scope = str(requested_scope).upper()
        if normalized_scope in {"ORGANIZATION_SUBTREE", "ORGANIZATION_LEVEL"} and not (
            organization_id or agent_context.get("organization_id")
        ):
            raise ValueError("Agent has no active organization for organization-scoped knowledge")
    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
                              IMPORTANCE, STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
                              WORKSPACE_ID)
        VALUES (AI_NEW_ID(), 'KNOWLEDGE', :title, :content, :summary, :category,
                :importance, 'ACTIVE', :owned_by_agent, NULL, :visibility,
                :wsid)
        RETURNING ENTITY_ID INTO :ret_id
    """
    params = {
        "title": title[:500],
        "content": content,
        "summary": summary,
        "category": category,
        "importance": importance,
        "owned_by_agent": owned_by_agent,
        "visibility": visibility,
        "wsid": workspace_id,
    }
    entity_id = execute_insert_returning_id(entity_sql, params)

    next_review = "CURRENT_TIMESTAMP + INTERVAL '7 days'" if DATABASE_DIALECT == "postgresql" else "CURRENT_TIMESTAMP + 7"
    meta_sql = f"""
        INSERT INTO KNOWLEDGE_META (ENTITY_ID, ENTITY_TYPE, DOMAIN, TOPIC, DIFFICULTY,
                                    REVIEW_COUNT, NEXT_REVIEW)
        VALUES (:eid, 'KNOWLEDGE', :domain, :topic, :difficulty, 0, {next_review})
    """
    execute(meta_sql, {
        "eid": entity_id,
        "domain": domain,
        "topic": topic,
        "difficulty": difficulty,
    })
    if owned_by_agent:
        capture_agent_knowledge_context(entity_id, owned_by_agent, sharing_scope=sharing_scope or (
            "PRINCIPAL_PRIVATE" if str(visibility).upper() == "PRIVATE" else "ORGANIZATION_SUBTREE"
        ), organization_id=organization_id, hierarchy_depth=hierarchy_depth,
            reason=creation_reason, context=agent_context)
    return entity_id


def get_knowledge(entity_id: str, principal_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY, e.CATEGORY,
               e.IMPORTANCE, e.STATUS, e.OWNED_BY_AGENT, e.SOURCE_AGENT, e.VISIBILITY,
               e.RETRIEVAL_COUNT,
               TO_CHAR(e.EXPIRES_AT, 'YYYY-MM-DD HH24:MI:SS') AS EXPIRES_AT,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               km.DOMAIN, km.TOPIC, km.DIFFICULTY, km.REVIEW_COUNT,
               TO_CHAR(km.LAST_REVIEWED, 'YYYY-MM-DD HH24:MI:SS') AS LAST_REVIEWED,
               TO_CHAR(km.NEXT_REVIEW, 'YYYY-MM-DD HH24:MI:SS') AS NEXT_REVIEW
        FROM ENTITIES e
        JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
                               AND km.ENTITY_TYPE = 'KNOWLEDGE'
        WHERE e.ENTITY_ID = :id AND e.ENTITY_TYPE = 'KNOWLEDGE'
          AND (:principal_id IS NULL OR """ + knowledge_access_predicate("e", ":principal_id") + """)
    """
    row = execute_query_one(sql, {"id": entity_id, "principal_id": principal_id})
    if row is None:
        return None
    result = _row_to_dict(row)
    result["knowledge_context"] = get_knowledge_context(entity_id)
    return result


def update_knowledge(entity_id: str, **kwargs) -> bool:
    entity_fields = {"title", "content", "summary", "category", "importance",
                     "status", "visibility", "expires_at"}
    meta_fields = {"domain", "topic", "difficulty"}

    entity_updates = {}
    meta_updates = {}

    for k, v in kwargs.items():
        lk = k.lower()
        if lk in entity_fields:
            entity_updates[lk] = v
        elif lk in meta_fields:
            meta_updates[lk] = v

    affected = 0

    if entity_updates:
        set_parts = [f"{k} = :{k}" for k in entity_updates]
        set_parts.append("UPDATED_AT = CURRENT_TIMESTAMP")
        entity_updates["id"] = entity_id
        sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'"
        affected += execute(sql, entity_updates)

    if meta_updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in meta_updates)
        meta_updates["eid"] = entity_id
        sql = f"UPDATE KNOWLEDGE_META SET {set_clause} WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'KNOWLEDGE'"
        affected += execute(sql, meta_updates)

    return affected > 0


def delete_knowledge(entity_id: str) -> bool:
    execute("DELETE FROM ENTITY_TAGS WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'", {"id": entity_id})
    execute("DELETE FROM KNOWLEDGE_META WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'", {"id": entity_id})
    execute("DELETE FROM ENTITY_EDGES WHERE (SOURCE_ID = :id AND SOURCE_TYPE = 'KNOWLEDGE') OR TARGET_ID = :id", {"id": str(entity_id)})
    execute("DELETE FROM ENTITY_EMBEDDINGS WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'", {"id": entity_id})
    sql = "DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'"
    return execute(sql, {"id": entity_id}) > 0


def search_knowledge(
    domain: Optional[str] = None,
    topic: Optional[str] = None,
    keyword: Optional[str] = None,
    difficulty: Optional[str] = None,
    workspace_id: Optional[str] = None,
    isolation_mode: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    principal_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    conditions = ["e.ENTITY_TYPE = 'KNOWLEDGE'"]
    params: Dict[str, Any] = {"lim": limit, "off": offset}

    if domain:
        conditions.append("km.DOMAIN = :domain")
        params["domain"] = domain
    if topic:
        conditions.append("km.TOPIC = :topic")
        params["topic"] = topic
    if difficulty:
        conditions.append("km.DIFFICULTY = :difficulty")
        params["difficulty"] = difficulty
    if keyword:
        conditions.append("(UPPER(e.TITLE) LIKE UPPER(:kw) OR UPPER(e.CONTENT) LIKE UPPER(:kw))")
        params["kw"] = f"%{keyword}%"
    if isolation_mode == 'SHARED':
        conditions.append("e.WORKSPACE_ID IS NULL")
    elif isolation_mode == 'ISOLATED' and workspace_id:
        conditions.append("e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id
    elif workspace_id:
        conditions.append("e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id
    # REST, MCP, and unified search pass the authenticated principal.  Keep
    # the legacy library call usable for migration tests, but never invent a
    # principal or apply a broken visibility predicate when none is supplied.
    if principal_id and identity_api.effective_access(principal_id, "agents.read.all").get("decision") != "ALLOW":
        legacy_scope = identity_api._agent_visibility_clause(principal_id)
        if ":principal_id" not in legacy_scope:
            conditions.append("1=1 /* SCOPE_CLAUSE: privileged constant scope */")
        else:
            conditions.append(knowledge_access_predicate("e", ":principal_id"))
            params["principal_id"] = principal_id

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY, e.CATEGORY,
               e.IMPORTANCE, e.STATUS, e.OWNED_BY_AGENT, e.SOURCE_AGENT, e.VISIBILITY,
               e.RETRIEVAL_COUNT,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               km.DOMAIN, km.TOPIC, km.DIFFICULTY, km.REVIEW_COUNT,
               TO_CHAR(km.LAST_REVIEWED, 'YYYY-MM-DD HH24:MI:SS') AS LAST_REVIEWED,
               TO_CHAR(km.NEXT_REVIEW, 'YYYY-MM-DD HH24:MI:SS') AS NEXT_REVIEW
        FROM ENTITIES e
        JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
                               AND km.ENTITY_TYPE = 'KNOWLEDGE'
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    return [_row_to_dict(r) for r in execute_query(sql, params)]


def search_knowledge_cursor(
    principal_id: str, *, page_size: int = 20, cursor: str = "", domain: Optional[str] = None,
    topic: Optional[str] = None, keyword: Optional[str] = None, difficulty: Optional[str] = None,
    workspace_id: Optional[str] = None, isolation_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a keyset page for the Knowledge inventory.

    The cursor is opaque and binds all search dimensions.  It is intentionally
    separate from retrieval APIs so a browser cannot turn an inventory cursor
    into an unrestricted text search continuation.
    """
    filters = {"domain": domain or "", "topic": topic or "", "keyword": keyword or "",
               "difficulty": difficulty or "", "workspace_id": workspace_id or "",
               "isolation_mode": isolation_mode or ""}
    context = cursor_pagination.resolve(principal_id, "knowledge", filters, "entity_id:asc", page_size, cursor)
    context.update({"principal_id": principal_id, "resource_key": "knowledge", "sort_key": "entity_id:asc"})
    conditions = ["e.ENTITY_TYPE = 'KNOWLEDGE'"]
    params: Dict[str, Any] = {"lim": int(context["page_size"]) + 1}
    if domain:
        conditions.append("km.DOMAIN = :domain")
        params["domain"] = domain
    if topic:
        conditions.append("km.TOPIC = :topic")
        params["topic"] = topic
    if difficulty:
        conditions.append("km.DIFFICULTY = :difficulty")
        params["difficulty"] = difficulty
    if keyword:
        conditions.append("(UPPER(e.TITLE) LIKE UPPER(:kw) OR UPPER(e.CONTENT) LIKE UPPER(:kw))")
        params["kw"] = f"%{keyword}%"
    if isolation_mode == "SHARED":
        conditions.append("e.WORKSPACE_ID IS NULL")
    elif isolation_mode == "ISOLATED" and workspace_id:
        conditions.append("e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id
    elif workspace_id:
        conditions.append("e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id
    if identity_api.effective_access(principal_id, "agents.read.all").get("decision") != "ALLOW":
        legacy_scope = identity_api._agent_visibility_clause(principal_id)
        if ":principal_id" not in legacy_scope:
            conditions.append("1=1 /* SCOPE_CLAUSE: privileged constant scope */")
        else:
            conditions.append(knowledge_access_predicate("e", ":principal_id"))
            params["principal_id"] = principal_id
    after = str(context["position"].get("entity_id") or "")
    if after:
        conditions.append("e.ENTITY_ID > :after")
        params["after"] = after
    rows = execute_query(
        "SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.SUMMARY, e.CATEGORY, e.IMPORTANCE, e.STATUS, "
        "e.OWNED_BY_AGENT, e.SOURCE_AGENT, e.VISIBILITY, e.RETRIEVAL_COUNT, e.CREATED_AT, e.UPDATED_AT, "
        "km.DOMAIN, km.TOPIC, km.DIFFICULTY, km.REVIEW_COUNT, km.LAST_REVIEWED, km.NEXT_REVIEW "
        "FROM ENTITIES e JOIN KNOWLEDGE_META km ON km.ENTITY_ID=e.ENTITY_ID AND km.ENTITY_TYPE='KNOWLEDGE' "
        "WHERE " + " AND ".join(conditions) + " ORDER BY e.ENTITY_ID FETCH FIRST :lim ROWS ONLY", params,
    )
    values = [_row_to_dict(row) for row in rows]
    result = cursor_pagination.page(values, context, lambda item: {"entity_id": str(item["entity_id"])})
    count_conditions = [condition for condition in conditions if condition != "e.ENTITY_ID > :after"]
    count_params = {key: value for key, value in params.items() if key not in {"lim", "after"}}
    try:
        total = execute_query_one(
            "SELECT COUNT(*) AS CNT FROM ENTITIES e JOIN KNOWLEDGE_META km "
            "ON km.ENTITY_ID=e.ENTITY_ID AND km.ENTITY_TYPE='KNOWLEDGE' WHERE " +
            " AND ".join(count_conditions),
            count_params,
        )
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def get_due_reviews(limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY, e.CATEGORY,
               e.IMPORTANCE, e.STATUS, e.OWNED_BY_AGENT, e.SOURCE_AGENT, e.VISIBILITY,
               e.RETRIEVAL_COUNT,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               km.DOMAIN, km.TOPIC, km.DIFFICULTY, km.REVIEW_COUNT,
               TO_CHAR(km.LAST_REVIEWED, 'YYYY-MM-DD HH24:MI:SS') AS LAST_REVIEWED,
               TO_CHAR(km.NEXT_REVIEW, 'YYYY-MM-DD HH24:MI:SS') AS NEXT_REVIEW
        FROM ENTITIES e
        JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
                               AND km.ENTITY_TYPE = 'KNOWLEDGE'
        WHERE km.NEXT_REVIEW <= CURRENT_TIMESTAMP AND e.STATUS = 'ACTIVE'
        ORDER BY km.NEXT_REVIEW ASC
        FETCH FIRST :lim ROWS ONLY
    """
    return [_row_to_dict(r) for r in execute_query(sql, {"lim": limit})]


def record_review(entity_id: str) -> bool:
    review_interval = (
        "CURRENT_TIMESTAMP + LEAST(POWER(2, REVIEW_COUNT + 1), 30) * INTERVAL '1 day'"
        if DATABASE_DIALECT == "postgresql"
        else "CURRENT_TIMESTAMP + LEAST(POWER(2, REVIEW_COUNT + 1), 30)"
    )
    sql = f"""
        UPDATE KNOWLEDGE_META
        SET REVIEW_COUNT = REVIEW_COUNT + 1,
            LAST_REVIEWED = CURRENT_TIMESTAMP,
            NEXT_REVIEW = {review_interval}
        WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'KNOWLEDGE'
    """
    return execute(sql, {"eid": entity_id}) > 0


def add_knowledge_tags(entity_id: str, tag_names: List[str]) -> int:
    added = 0
    for tag_name in tag_names:
        tag_row = execute_query_one(
            "SELECT TAG_ID FROM TAGS WHERE TAG_NAME = :tag_name",
            {"tag_name": tag_name},
        )
        if tag_row is None:
            try:
                execute("INSERT INTO TAGS (TAG_NAME) VALUES (:tag_name)", {"tag_name": tag_name})
            except Exception:
                pass
            tag_row = execute_query_one(
                "SELECT TAG_ID FROM TAGS WHERE TAG_NAME = :tag_name",
                {"tag_name": tag_name},
            )
        if tag_row is None:
            continue

        tag_id = tag_row["tag_id"]
        existing = execute_query_one(
            "SELECT TAG_ID FROM ENTITY_TAGS WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'KNOWLEDGE' AND TAG_ID = :tid",
            {"eid": entity_id, "tid": tag_id},
        )
        if existing is None:
            try:
                execute(
                    "INSERT INTO ENTITY_TAGS (ENTITY_ID, ENTITY_TYPE, TAG_ID) VALUES (:eid, 'KNOWLEDGE', :tid)",
                    {"eid": entity_id, "tid": tag_id},
                )
                added += 1
            except Exception:
                pass
    return added


def get_knowledge_tags(entity_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT t.TAG_ID, t.TAG_NAME, t.TAG_GROUP
        FROM ENTITY_TAGS et
        JOIN TAGS t ON et.TAG_ID = t.TAG_ID
        WHERE et.ENTITY_ID = :id AND et.ENTITY_TYPE = 'KNOWLEDGE'
    """
    rows = execute_query(sql, {"id": entity_id})
    return [
        {"tag_id": r["tag_id"], "tag_name": r["tag_name"], "tag_group": r.get("tag_group")}
        for r in rows
    ]


def remove_knowledge_tag(entity_id: str, tag_id: int) -> bool:
    sql = """
        DELETE FROM ENTITY_TAGS
        WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE' AND TAG_ID = :tag_id
    """
    return execute(sql, {"id": entity_id, "tag_id": tag_id}) > 0


def add_edge(
    source_id: str,
    source_type: str,
    target_id: str,
    edge_type: str,
    strength: float = 1.0,
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    sql = """
        INSERT INTO ENTITY_EDGES (EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                                  STRENGTH, CONFIDENCE, METADATA)
        VALUES ('E_' || AI_NEW_ID(), :source_id, :source_type, :target_id, :edge_type,
                :strength, :confidence, :metadata)
        RETURNING EDGE_ID INTO :ret_id
    """
    params = {
        "source_id": source_id,
        "source_type": source_type,
        "target_id": target_id,
        "edge_type": edge_type,
        "strength": strength,
        "confidence": confidence,
        "metadata": json.dumps(metadata) if metadata else None,
    }
    return execute_insert_returning_id(sql, params, id_column="EDGE_ID")


def get_edges(entity_id: str, direction: str = "both") -> List[Dict[str, Any]]:
    if direction == "outgoing":
        sql = """
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM ENTITY_EDGES
            WHERE SOURCE_ID = :id
            ORDER BY CREATED_AT DESC
        """
    elif direction == "incoming":
        sql = """
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM ENTITY_EDGES
            WHERE TARGET_ID = :id
            ORDER BY CREATED_AT DESC
        """
    else:
        sql = """
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   'outgoing' AS DIRECTION
            FROM ENTITY_EDGES
            WHERE SOURCE_ID = :id
            UNION ALL
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   'incoming' AS DIRECTION
            FROM ENTITY_EDGES
            WHERE TARGET_ID = :id
            ORDER BY CREATED_AT DESC
        """
    rows = execute_query(sql, {"id": entity_id})
    result = []
    for r in rows:
        edge = {
            "edge_id": r.get("edge_id"),
            "source_id": r.get("source_id"),
            "source_type": r.get("source_type"),
            "target_id": r.get("target_id"),
            "edge_type": r.get("edge_type"),
            "strength": r.get("strength"),
            "confidence": r.get("confidence"),
            "metadata": r.get("metadata"),
            "created_at": r.get("created_at"),
        }
        if direction == "both":
            edge["direction"] = r.get("direction")
        if isinstance(edge["metadata"], str):
            try:
                edge["metadata"] = json.loads(edge["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(edge)
    return result


def count_knowledge(domain: Optional[str] = None) -> int:
    if domain:
        sql = """
            SELECT COUNT(*) AS CNT
            FROM ENTITIES e
            JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID AND km.ENTITY_TYPE = 'KNOWLEDGE'
            WHERE e.ENTITY_TYPE = 'KNOWLEDGE' AND km.DOMAIN = :domain
        """
        row = execute_query_one(sql, {"domain": domain})
    else:
        sql = "SELECT COUNT(*) AS CNT FROM ENTITIES WHERE ENTITY_TYPE = 'KNOWLEDGE'"
        row = execute_query_one(sql)
    return row["cnt"] if row else 0


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entity_id": row.get("entity_id"),
        "entity_type": row.get("entity_type"),
        "title": row.get("title"),
        "content": row.get("content"),
        "summary": row.get("summary"),
        "category": row.get("category"),
        "importance": row.get("importance"),
        "status": row.get("status"),
        "owned_by_agent": row.get("owned_by_agent"),
        "source_agent": row.get("source_agent"),
        "visibility": row.get("visibility"),
        "retrieval_count": row.get("retrieval_count"),
        "expires_at": row.get("expires_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "domain": row.get("domain"),
        "topic": row.get("topic"),
        "difficulty": row.get("difficulty"),
        "review_count": row.get("review_count"),
        "last_reviewed": row.get("last_reviewed"),
        "next_review": row.get("next_review"),
    }


# -- D4: Advanced Knowledge Management (v3.7.5) --

def merge_knowledge(source_id: str, target_id: str, strategy: str = "UNION") -> Dict[str, Any]:
    """Merge two knowledge entries using the specified strategy."""
    source = get_knowledge(source_id)
    target = get_knowledge(target_id)
    if not source or not target:
        return {"error": "Source or target not found"}

    if strategy == "OVERWRITE":
        execute(
            "UPDATE ENTITIES SET CONTENT = :content, UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :tid",
            {"content": source.get("content", ""), "tid": target_id},
        )
        execute("UPDATE ENTITIES SET VISIBILITY = 'PRIVATE' WHERE ENTITY_ID = :sid", {"sid": source_id})
        return {"strategy": strategy, "target_id": target_id, "source_archived": True}

    elif strategy == "UNION":
        merged_content = (target.get("content", "") or "") + "\n\n---\n\n" + (source.get("content", "") or "")
        execute(
            "UPDATE ENTITIES SET CONTENT = :content, UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :tid",
            {"content": merged_content, "tid": target_id},
        )
        execute("UPDATE ENTITIES SET VISIBILITY = 'PRIVATE' WHERE ENTITY_ID = :sid", {"sid": source_id})
        return {"strategy": strategy, "target_id": target_id, "merged_length": len(merged_content)}

    elif strategy == "WEIGHTED":
        source_strength = float(source.get("metadata", {}).get("strength", 0.5)) if isinstance(source.get("metadata"), dict) else 0.5
        target_strength = float(target.get("metadata", {}).get("strength", 0.5)) if isinstance(target.get("metadata"), dict) else 0.5
        total = source_strength + target_strength
        if total == 0:
            total = 1
        merged_content = source.get("content", "") or ""
        execute(
            "UPDATE ENTITIES SET CONTENT = :content, UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :tid",
            {"content": merged_content, "tid": target_id},
        )
        return {"strategy": strategy, "target_id": target_id, "source_weight": source_strength / total}

    return {"error": f"Unknown strategy: {strategy}"}


def detect_knowledge_conflicts(workspace_id: str) -> List[Dict[str, Any]]:
    """Detect knowledge entries with similar titles but different content in the same workspace."""
    rows = execute_query(
        """SELECT a.ENTITY_ID as id_a, a.TITLE as title_a, a.CONTENT as content_a,
                  b.ENTITY_ID as id_b, b.TITLE as title_b, b.CONTENT as content_b
           FROM ENTITIES a
           JOIN ENTITIES b ON a.ENTITY_ID < b.ENTITY_ID
           WHERE a.ENTITY_TYPE = 'KNOWLEDGE' AND b.ENTITY_TYPE = 'KNOWLEDGE'
             AND a.WORKSPACE_ID = :wid AND b.WORKSPACE_ID = :wid
             AND (UPPER(a.TITLE) = UPPER(b.TITLE)
                  OR DBMS_LOB.GETLENGTH(a.CONTENT) > 0 AND DBMS_LOB.GETLENGTH(b.CONTENT) > 0
                  AND DBMS_LOB.SUBSTR(a.CONTENT, 200, 1) = DBMS_LOB.SUBSTR(b.CONTENT, 200, 1))
           FETCH FIRST 50 ROWS ONLY""",
        {"wid": workspace_id},
    )
    conflicts = []
    for r in rows:
        if r.get("content_a") != r.get("content_b"):
            conflicts.append({
                "id_a": r["id_a"], "id_b": r["id_b"],
                "title": r.get("title_a") or r.get("title_b"),
                "conflict_type": "content_mismatch",
            })
    return conflicts
