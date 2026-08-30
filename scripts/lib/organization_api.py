"""Portable v4.3.1 organization governance domain services.

Relational organization facts are authoritative.  This module intentionally
contains no HTTP or property-graph dependency: callers receive a bounded graph
projection only after database-side scope filtering, while every mutation is
recorded as a semantic draft operation and published in one transaction.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import connection, identity_api


READ_ACTION = "organizations.read"
PEOPLE_ACTION = "organizations.people.read"
AGENT_ACTION = "organizations.agents.read"
ANOMALY_ACTION = "organizations.anomalies.read"
CHANGE_ACTION = "organizations.changes.write"
CREATE_ACTION = "organizations.changes.create"
SUBMIT_ACTION = "organizations.changes.submit"
APPROVE_ACTION = "organizations.changes.approve"
PUBLISH_ACTION = "organizations.changes.publish"
HISTORY_ACTION = "organizations.history.read"
SYNC_ACTION = "organizations.sync.manage"

MEMBERSHIP_KINDS = {"PRIMARY", "SECONDARY"}
REPORTING_TYPES = {"DIRECT", "DOTTED", "PROJECT_LEAD"}
AGENT_ROLES = {"PRIMARY_OWNER", "SPONSOR", "OPERATOR", "VIEWER"}
CHANGE_STATUSES = {"DRAFT", "VALIDATED", "PENDING_APPROVAL", "APPROVED", "PUBLISHING", "SCHEDULED", "PUBLISHED", "CANCELLED", "REJECTED"}
OPERATION_TYPES = {
    "CREATE_ORGANIZATION", "RENAME_ORGANIZATION", "UPDATE_ORGANIZATION",
    "MOVE_ORGANIZATION", "RETIRE_ORGANIZATION", "ADD_MEMBERSHIP",
    "END_MEMBERSHIP", "SET_REPORTING", "END_REPORTING",
    "SET_AGENT_RELATIONSHIP", "END_AGENT_RELATIONSHIP",
}
LOW_RISK_OPERATIONS = {
    "CREATE_ORGANIZATION", "RENAME_ORGANIZATION", "UPDATE_ORGANIZATION",
    "ADD_MEMBERSHIP", "END_MEMBERSHIP",
}
MAX_PAGE = 500
MAX_GRAPH_NODES = 1000
MAX_DRAFT_OPERATIONS = 1000
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_RECORDS = 100_000


def _approvals_enabled() -> bool:
    """Use the edition boundary for organization publication decisions."""
    try:
        from lib import edition_features
    except ModuleNotFoundError:
        try:
            from shared.lib import edition_features
        except ModuleNotFoundError:
            return True
    return bool(edition_features.has_feature("approvals"))


class OrganizationError(ValueError):
    """Safe organization service error that does not enumerate hidden facts."""


class OrganizationConflict(OrganizationError):
    """Optimistic concurrency or source-authority conflict."""


def _row(value: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(key).lower(): item for key, item in dict(value).items()} if value else None


def _rows(values: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(value) or {} for value in values]


def _json(value: Any) -> str:
    def encode(item: Any) -> Any:
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, (bytes, bytearray)):
            return bytes(item).hex()
        raise TypeError(f"unsupported organization JSON value: {type(item).__name__}")

    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=encode)


def _load_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return default


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(prefix: str) -> str:
    return identity_api._id(prefix)


def _dialect() -> str:
    return str(getattr(connection, "DATABASE_DIALECT", "") or "").lower()


def _limit(bind: str = "limit") -> str:
    if _dialect() in {"postgresql", "pg"}:
        return "LIMIT :" + bind
    return "FETCH FIRST :" + bind + " ROWS ONLY"


def _bounded(value: int, maximum: int = MAX_PAGE) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError) as exc:
        raise OrganizationError("limit is invalid") from exc


def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    result = str(value or "").strip()
    if (required and not result) or len(result) > maximum or "\x00" in result:
        raise OrganizationError(f"{field} is invalid")
    return result


def _access(actor: str, action: str) -> Dict[str, Any]:
    actor = _text(actor, "actor", 256, required=True)
    decision = identity_api.effective_access(actor, action)
    if decision.get("decision") != "ALLOW":
        raise PermissionError(f"permission denied: {action}")
    return decision


def _scope_clause(actor: str, alias: str = "o", action: str = READ_ACTION) -> tuple[str, Dict[str, Any]]:
    """Compile organization visibility from effective scopes using closure facts."""
    access = _access(actor, action)
    scopes = {str(item).upper() for item in access.get("scopes", [])}
    if "ALL" in scopes:
        return "1 = 1", {}
    clauses: List[str] = []
    params: Dict[str, Any] = {"actor_principal_id": actor}
    if scopes & {"ORG_SUBTREE", "OWNED", "ASSIGNED"}:
        if "ORG_SUBTREE" in scopes:
            clauses.append(
                "EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS actor_membership "
                "JOIN CX_ORGANIZATION_CLOSURE actor_closure "
                "ON actor_closure.ANCESTOR_ID = actor_membership.ORGANIZATION_ID "
                f"WHERE actor_closure.DESCENDANT_ID = {alias}.ORGANIZATION_ID "
                "AND actor_membership.PRINCIPAL_ID = :actor_principal_id "
                "AND actor_membership.MEMBERSHIP_KIND = 'PRIMARY' "
                "AND actor_membership.STATUS = 'ACTIVE' "
                "AND (actor_membership.VALID_UNTIL IS NULL OR actor_membership.VALID_UNTIL > CURRENT_TIMESTAMP))"
            )
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS actor_membership "
                f"WHERE actor_membership.ORGANIZATION_ID = {alias}.ORGANIZATION_ID "
                "AND actor_membership.PRINCIPAL_ID = :actor_principal_id "
                "AND actor_membership.MEMBERSHIP_KIND = 'PRIMARY' "
                "AND actor_membership.STATUS = 'ACTIVE' "
                "AND (actor_membership.VALID_UNTIL IS NULL OR actor_membership.VALID_UNTIL > CURRENT_TIMESTAMP))"
            )
    if "DIRECT_REPORTS" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_REPORTING_RELATIONSHIPS direct_report "
            "JOIN CX_ORGANIZATION_MEMBERS report_membership "
            "ON report_membership.PRINCIPAL_ID = direct_report.PRINCIPAL_ID "
            f"WHERE report_membership.ORGANIZATION_ID = {alias}.ORGANIZATION_ID "
            "AND direct_report.MANAGER_PRINCIPAL_ID = :actor_principal_id "
            "AND direct_report.RELATIONSHIP_TYPE = 'DIRECT' "
            "AND direct_report.STATUS = 'ACTIVE' AND report_membership.STATUS = 'ACTIVE' "
            "AND (direct_report.VALID_UNTIL IS NULL OR direct_report.VALID_UNTIL > CURRENT_TIMESTAMP))"
        )
    scope_clause = "(" + " OR ".join(clauses) + ")" if clauses else "1 = 0"
    if "SECURITY_DOMAIN" in scopes:
        domain_clause = (
            f"EXISTS (SELECT 1 FROM CX_DOMAIN_MEMBERS actor_domain WHERE actor_domain.SECURITY_DOMAIN_ID = {alias}.SECURITY_DOMAIN_ID "
            "AND actor_domain.PRINCIPAL_ID = :actor_principal_id AND actor_domain.STATUS = 'ACTIVE')"
        )
        scope_clause = f"({scope_clause}) AND ({domain_clause})"
    return scope_clause, params


def _query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    try:
        return _rows(connection.execute_query(sql, params or {}))
    except (OrganizationError, PermissionError):
        raise
    except Exception as exc:
        raise OrganizationError("organization governance data is unavailable") from exc


def _query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    try:
        return _row(connection.execute_query_one(sql, params or {}))
    except (OrganizationError, PermissionError):
        raise
    except Exception as exc:
        raise OrganizationError("organization governance data is unavailable") from exc


def _visible_organization(actor: str, organization_id: str, action: str = READ_ACTION) -> bool:
    clause, params = _scope_clause(actor, "o", action)
    params["organization_id"] = _text(organization_id, "organization_id", 256, required=True)
    return bool(_query_one(
        "SELECT o.ORGANIZATION_ID FROM CX_ORGANIZATIONS o "
        "WHERE o.ORGANIZATION_ID = :organization_id AND o.STATUS <> 'DELETED' AND " + clause,
        params,
    ))


def _require_visible(actor: str, organization_id: str, action: str = READ_ACTION) -> None:
    if not _visible_organization(actor, organization_id, action):
        raise OrganizationError("organization is unavailable")


def list_roots(actor_principal_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
    clause, params = _scope_clause(actor_principal_id, "o")
    params["limit"] = _bounded(limit)
    # A delegated subtree root is a root relative to the caller's visible set.
    parent_clause, _ = _scope_clause(actor_principal_id, "parent_o")
    return _query(
        "SELECT o.ORGANIZATION_ID, o.PARENT_ID, o.ORGANIZATION_CODE, o.ORGANIZATION_NAME, "
        "o.ORGANIZATION_TYPE, o.IS_LEGAL_ENTITY, o.SORT_ORDER, o.STATUS, o.ROW_VERSION, o.UPDATED_AT "
        "FROM CX_ORGANIZATIONS o WHERE o.STATUS <> 'DELETED' AND " + clause + " "
        "AND (o.PARENT_ID IS NULL OR NOT EXISTS (SELECT 1 FROM CX_ORGANIZATIONS parent_o "
        "WHERE parent_o.ORGANIZATION_ID = o.PARENT_ID AND parent_o.STATUS <> 'DELETED' AND " + parent_clause + ")) "
        "ORDER BY o.SORT_ORDER, o.ORGANIZATION_NAME, o.ORGANIZATION_ID " + _limit(), params,
    )


def list_options(actor_principal_id: str, *, limit: int = 500) -> List[Dict[str, Any]]:
    """Return a flat, scoped organization list for governed assignment forms."""
    clause, params = _scope_clause(actor_principal_id, "o", "organizations.members.manage")
    params["limit"] = _bounded(limit)
    return _query(
        "SELECT o.ORGANIZATION_ID, o.PARENT_ID, o.ORGANIZATION_CODE, o.ORGANIZATION_NAME, "
        "o.ORGANIZATION_TYPE, o.SORT_ORDER, o.STATUS FROM CX_ORGANIZATIONS o "
        "WHERE o.STATUS = 'ACTIVE' AND " + clause + " "
        "ORDER BY o.SORT_ORDER, o.ORGANIZATION_NAME, o.ORGANIZATION_ID " + _limit(),
        params,
    )


def list_children(actor_principal_id: str, parent_id: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    _require_visible(actor_principal_id, parent_id)
    clause, params = _scope_clause(actor_principal_id, "o")
    params.update({"parent_id": parent_id, "limit": _bounded(limit)})
    return _query(
        "SELECT o.ORGANIZATION_ID, o.PARENT_ID, o.ORGANIZATION_CODE, o.ORGANIZATION_NAME, "
        "o.ORGANIZATION_TYPE, o.IS_LEGAL_ENTITY, o.SORT_ORDER, o.STATUS, o.ROW_VERSION, "
        "CASE WHEN EXISTS (SELECT 1 FROM CX_ORGANIZATIONS child WHERE child.PARENT_ID = o.ORGANIZATION_ID "
        "AND child.STATUS <> 'DELETED') THEN 1 ELSE 0 END AS HAS_CHILDREN "
        "FROM CX_ORGANIZATIONS o WHERE o.PARENT_ID = :parent_id AND o.STATUS <> 'DELETED' AND " + clause + " "
        "ORDER BY o.SORT_ORDER, o.ORGANIZATION_NAME, o.ORGANIZATION_ID " + _limit(), params,
    )


def search(actor_principal_id: str, query: str, limit: int = 50) -> List[Dict[str, Any]]:
    term = _text(query, "query", 256, required=True)
    if len(term) < 2:
        raise OrganizationError("query must contain at least two characters")
    # Treat wildcard metacharacters as separators, not caller-controlled SQL patterns.
    pattern = "%" + " ".join(term.replace("%", " ").replace("_", " ").upper().split()) + "%"
    clause, params = _scope_clause(actor_principal_id, "o")
    params.update({"pattern": pattern, "limit": _bounded(limit)})
    return _query(
        "SELECT o.ORGANIZATION_ID, o.PARENT_ID, o.ORGANIZATION_CODE, o.ORGANIZATION_NAME, "
        "o.ORGANIZATION_TYPE, o.STATUS, o.ROW_VERSION FROM CX_ORGANIZATIONS o "
        "WHERE o.STATUS <> 'DELETED' AND " + clause + " AND "
        "(UPPER(o.ORGANIZATION_NAME) LIKE :pattern OR UPPER(o.ORGANIZATION_CODE) LIKE :pattern) "
        "ORDER BY o.ORGANIZATION_NAME, o.ORGANIZATION_ID " + _limit(), params,
    )


def get_detail(actor_principal_id: str, organization_id: str) -> Dict[str, Any]:
    clause, params = _scope_clause(actor_principal_id, "o")
    params["organization_id"] = _text(organization_id, "organization_id", 256, required=True)
    row = _query_one(
        "SELECT o.ORGANIZATION_ID, o.PARENT_ID, o.ORGANIZATION_CODE, o.ORGANIZATION_NAME, "
        "o.ORGANIZATION_TYPE, o.IS_LEGAL_ENTITY, o.SORT_ORDER, o.RESPONSIBLE_PRINCIPAL_ID, "
        "o.SECURITY_DOMAIN_ID, o.VALID_FROM, o.VALID_UNTIL, o.SOURCE_TYPE, o.EXTERNAL_OBJECT_ID, "
        "o.STATUS, o.ROW_VERSION, o.CREATED_AT, o.UPDATED_AT FROM CX_ORGANIZATIONS o "
        "WHERE o.ORGANIZATION_ID = :organization_id AND o.STATUS <> 'DELETED' AND " + clause,
        params,
    )
    if not row:
        raise OrganizationError("organization is unavailable")
    return row


def list_people(actor_principal_id: str, organization_id: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    _require_visible(actor_principal_id, organization_id, PEOPLE_ACTION)
    return _query(
        "SELECT m.MEMBERSHIP_ID, m.ORGANIZATION_ID, m.PRINCIPAL_ID, m.MEMBERSHIP_KIND, "
        "m.MEMBERSHIP_ROLE, m.VALID_FROM, m.VALID_UNTIL, m.SOURCE_TYPE, m.STATUS, m.ROW_VERSION, "
        "p.DISPLAY_NAME, i.USERNAME, i.EMAIL, p.STATUS AS PRINCIPAL_STATUS, "
        "(SELECT COUNT(*) FROM CX_AGENT_RELATIONSHIPS ar WHERE ar.PRINCIPAL_ID = m.PRINCIPAL_ID "
        "AND ar.STATUS = 'ACTIVE') AS AGENT_RELATIONSHIP_COUNT "
        "FROM CX_ORGANIZATION_MEMBERS m JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = m.PRINCIPAL_ID "
        "LEFT JOIN CX_HUMAN_IDENTITIES i ON i.PRINCIPAL_ID = m.PRINCIPAL_ID AND i.STATUS = 'ACTIVE' "
        "WHERE m.ORGANIZATION_ID = :organization_id AND m.STATUS = 'ACTIVE' "
        "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "ORDER BY m.MEMBERSHIP_KIND, i.USERNAME, m.PRINCIPAL_ID " + _limit(),
        {"organization_id": organization_id, "limit": _bounded(limit)},
    )


def list_agent_relationships(actor_principal_id: str, *, organization_id: str = "", principal_id: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    _access(actor_principal_id, AGENT_ACTION)
    if not organization_id and not principal_id:
        raise OrganizationError("organization_id or principal_id is required")
    params: Dict[str, Any] = {"limit": _bounded(limit)}
    where = ""
    if organization_id:
        _require_visible(actor_principal_id, organization_id, AGENT_ACTION)
        params["organization_id"] = organization_id
        where = (
            "EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS m WHERE m.PRINCIPAL_ID = ar.PRINCIPAL_ID "
            "AND m.ORGANIZATION_ID = :organization_id AND m.STATUS = 'ACTIVE')"
        )
    else:
        principal_id = _text(principal_id, "principal_id", 256, required=True)
        if not identity_api._principal_visible_to(actor_principal_id, principal_id):
            raise OrganizationError("principal is unavailable")
        params["target_principal_id"] = principal_id
        where = "ar.PRINCIPAL_ID = :target_principal_id"
    rows = _query(
        "SELECT ar.RELATIONSHIP_ID, ar.AGENT_ID, ar.PRINCIPAL_ID, ar.RELATIONSHIP_ROLE, "
        "ar.RESPONSIBLE_GROUP_ID, ar.STATUS, p.STATUS AS AGENT_STATUS, p.UPDATED_AT "
        "FROM CX_AGENT_RELATIONSHIPS ar JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = ar.AGENT_ID "
        "WHERE ar.STATUS = 'ACTIVE' AND p.PRINCIPAL_TYPE = 'AGENT' AND " + where + " "
        "ORDER BY ar.PRINCIPAL_ID, ar.RELATIONSHIP_ROLE, ar.AGENT_ID " + _limit(), params,
    )
    # Recheck each Agent through the canonical identity visibility decision.
    return [row for row in rows if identity_api._agent_visible_to(actor_principal_id, str(row.get("agent_id") or ""))]


def list_anomalies(actor_principal_id: str, *, organization_id: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    access = _access(actor_principal_id, ANOMALY_ACTION)
    params: Dict[str, Any] = {"limit": _bounded(limit)}
    membership_filter = ""
    if organization_id:
        _require_visible(actor_principal_id, organization_id, ANOMALY_ACTION)
        params["organization_id"] = organization_id
        membership_filter = (
            " AND EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS am WHERE am.PRINCIPAL_ID = p.PRINCIPAL_ID "
            "AND am.ORGANIZATION_ID = :organization_id AND am.STATUS = 'ACTIVE')"
        )
    elif "ALL" not in {str(item).upper() for item in access.get("scopes", [])}:
        org_clause, scope_params = _scope_clause(actor_principal_id, "anomaly_o", ANOMALY_ACTION)
        params.update(scope_params)
        membership_filter = (
            " AND EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS anomaly_m "
            "JOIN CX_ORGANIZATIONS anomaly_o ON anomaly_o.ORGANIZATION_ID = anomaly_m.ORGANIZATION_ID "
            "WHERE anomaly_m.PRINCIPAL_ID = p.PRINCIPAL_ID AND anomaly_m.STATUS = 'ACTIVE' AND " + org_clause + ")"
        )
    return _query(
        "SELECT p.PRINCIPAL_ID AS SUBJECT_ID, 'HUMAN_WITHOUT_PRIMARY_ORG' AS ANOMALY_TYPE, p.DISPLAY_NAME, "
        "(SELECT MIN(i.USERNAME) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND i.STATUS = 'ACTIVE') AS USERNAME, p.STATUS, p.UPDATED_AT FROM CX_PRINCIPALS p "
        "WHERE p.PRINCIPAL_TYPE = 'HUMAN' AND p.STATUS = 'ACTIVE' "
        "AND NOT EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS m WHERE m.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND m.MEMBERSHIP_KIND = 'PRIMARY' AND m.STATUS = 'ACTIVE')" + membership_filter + " "
        "ORDER BY p.UPDATED_AT DESC " + _limit(), params,
    )


def _anomaly_graph(
    anomalies: List[Dict[str, Any]], organization_id: str, organization_label: str
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a focused exception graph instead of repeating the hierarchy."""
    if not anomalies:
        return [], []
    root_id = "org:" + organization_id
    nodes: List[Dict[str, Any]] = [{
        "id": root_id, "organization_id": organization_id, "kind": "ORGANIZATION",
        "label": organization_label or organization_id, "anomaly_count": len(anomalies),
    }]
    edges: List[Dict[str, Any]] = []
    for index, item in enumerate(anomalies):
        subject_id = str(item.get("subject_id") or "")
        if not subject_id:
            continue
        node_id = "anomaly:" + subject_id
        anomaly_type = str(item.get("anomaly_type") or "ANOMALOUS_RELATIONSHIP")
        nodes.append({
            "id": node_id, "principal_id": subject_id, "kind": "ANOMALY",
            "display_name": item.get("display_name"),
            "label": item.get("display_name") or item.get("username") or "Unnamed person", "anomaly": True,
            "anomaly_type": anomaly_type, "status": item.get("status"),
        })
        edges.append({
            "id": f"anomaly-edge:{index}:{subject_id}", "from": root_id, "to": node_id,
            "kind": anomaly_type, "label": anomaly_type,
        })
    return nodes, edges


def assemble_graph(actor_principal_id: str, organization_id: str, *, mode: str = "ORGANIZATION", include_children: bool = True, limit: int = 300) -> Dict[str, Any]:
    mode = str(mode or "ORGANIZATION").upper()
    if mode not in {"ORGANIZATION", "PEOPLE", "AGENTS", "ANOMALIES"}:
        raise OrganizationError("graph mode is invalid")
    budget = _bounded(limit, MAX_GRAPH_NODES)
    root = get_detail(actor_principal_id, organization_id)
    organizations = [root]
    if include_children and budget > 1:
        organizations.extend(list_children(actor_principal_id, organization_id, limit=budget - 1))
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for item in organizations:
        oid = str(item["organization_id"])
        nodes.append({"id": "org:" + oid, "organization_id": oid, "kind": "ORGANIZATION", "label": item.get("organization_name") or oid,
                      "parent_id": item.get("parent_id"), "sort_order": int(item.get("sort_order") or 0),
                      "organization_type": item.get("organization_type"), "status": item.get("status")})
        if item.get("parent_id") and any(str(parent.get("organization_id")) == str(item["parent_id"]) for parent in organizations):
            edges.append({"id": f"org-edge:{item['parent_id']}:{oid}", "from": "org:" + str(item["parent_id"]), "to": "org:" + oid, "kind": "CONTAINS"})
    remaining = budget - len(nodes)
    if mode in {"PEOPLE", "AGENTS"} and remaining > 0:
        people = list_people(actor_principal_id, organization_id, limit=remaining)
        for person in people[:remaining]:
            pid = str(person["principal_id"])
            nodes.append({"id": "person:" + pid, "principal_id": pid, "kind": "PERSON",
                          "display_name": person.get("display_name"),
                          "label": person.get("display_name") or person.get("username") or "Unnamed person",
                          "membership_kind": person.get("membership_kind"), "status": person.get("principal_status")})
            edges.append({"id": f"member:{person['membership_id']}", "from": "org:" + organization_id, "to": "person:" + pid, "kind": str(person.get("membership_kind") or "MEMBER")})
        remaining = budget - len(nodes)
        if mode == "AGENTS" and remaining > 0:
            for rel in list_agent_relationships(actor_principal_id, organization_id=organization_id, limit=remaining):
                aid, pid = str(rel["agent_id"]), str(rel["principal_id"])
                if not any(node["id"] == "agent:" + aid for node in nodes):
                    nodes.append({"id": "agent:" + aid, "kind": "AGENT", "label": aid, "status": rel.get("agent_status")})
                if any(node["id"] == "person:" + pid for node in nodes):
                    edges.append({"id": "agent-rel:" + str(rel["relationship_id"]), "from": "person:" + pid, "to": "agent:" + aid, "kind": rel.get("relationship_role")})
                if len(nodes) >= budget:
                    break
    anomalies: List[Dict[str, Any]] = []
    if mode == "ANOMALIES":
        anomalies = list_anomalies(actor_principal_id, organization_id=organization_id, limit=max(1, remaining))
        nodes, edges = _anomaly_graph(
            anomalies, organization_id, str(root.get("organization_name") or organization_id)
        )
    nodes.sort(key=lambda item: (str(item.get("kind")), int(item.get("sort_order") or 0), str(item.get("label")), str(item["id"])))
    edges.sort(key=lambda item: (str(item.get("kind")), str(item["from"]), str(item["to"]), str(item["id"])))
    return {"focus_id": organization_id, "mode": mode, "layout": "HIERARCHICAL", "nodes": nodes,
            "edges": edges, "anomalies": anomalies, "truncated": len(nodes) >= budget}


def organization_graph(
    actor: str,
    root_id: str = "",
    mode: str = "organization",
    depth: int = 2,
    limit: int = 300,
) -> Dict[str, Any]:
    """Return a bounded, deterministic graph for direct Web integration."""
    normalized_mode = str(mode or "organization").upper()
    if normalized_mode not in {"ORGANIZATION", "PEOPLE", "AGENTS", "ANOMALIES"}:
        raise OrganizationError("graph mode is invalid")
    try:
        bounded_depth = max(0, min(int(depth), 10))
    except (TypeError, ValueError) as exc:
        raise OrganizationError("graph depth is invalid") from exc
    budget = _bounded(limit, MAX_GRAPH_NODES)
    roots = [get_detail(actor, root_id)] if root_id else list_roots(actor, limit=min(budget, 100))
    organizations: List[Dict[str, Any]] = list(roots)
    frontier = list(roots)
    for _ in range(bounded_depth):
        next_frontier: List[Dict[str, Any]] = []
        for parent in frontier:
            remaining = budget - len(organizations)
            if remaining <= 0:
                break
            children = list_children(actor, str(parent["organization_id"]), limit=remaining)
            organizations.extend(children)
            next_frontier.extend(children)
        frontier = next_frontier
        if not frontier or len(organizations) >= budget:
            break
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    visible_ids = {str(item["organization_id"]) for item in organizations}
    for item in organizations:
        oid = str(item["organization_id"])
        nodes.append({"id": "org:" + oid, "kind": "ORGANIZATION", "label": item.get("organization_name") or oid,
                      "parent_id": item.get("parent_id"), "sort_order": int(item.get("sort_order") or 0),
                      "organization_type": item.get("organization_type"), "status": item.get("status")})
        if item.get("parent_id") is not None and str(item["parent_id"]) in visible_ids:
            edges.append({"id": f"org-edge:{item['parent_id']}:{oid}", "from": "org:" + str(item["parent_id"]),
                          "to": "org:" + oid, "kind": "CONTAINS"})
    focus = str(root_id or (roots[0]["organization_id"] if len(roots) == 1 else ""))
    remaining = budget - len(nodes)
    anomalies: List[Dict[str, Any]] = []
    # People and Agent expansion is intentionally focused on one organization;
    # callers can progressively request another node instead of materializing a company.
    if focus and normalized_mode in {"PEOPLE", "AGENTS"} and remaining > 0:
        people = list_people(actor, focus, limit=remaining)
        for person in people[:remaining]:
            pid = str(person["principal_id"])
            nodes.append({"id": "person:" + pid, "principal_id": pid, "kind": "PERSON",
                          "display_name": person.get("display_name"),
                          "label": person.get("display_name") or person.get("username") or "Unnamed person",
                          "membership_kind": person.get("membership_kind"), "status": person.get("principal_status")})
            edges.append({"id": f"member:{person['membership_id']}", "from": "org:" + focus,
                          "to": "person:" + pid, "kind": str(person.get("membership_kind") or "MEMBER")})
        if normalized_mode == "AGENTS" and len(nodes) < budget:
            for rel in list_agent_relationships(actor, organization_id=focus, limit=budget - len(nodes)):
                aid, pid = str(rel["agent_id"]), str(rel["principal_id"])
                if not any(node["id"] == "agent:" + aid for node in nodes):
                    nodes.append({"id": "agent:" + aid, "agent_id": aid, "kind": "AGENT", "label": aid,
                                  "status": rel.get("agent_status")})
                if any(node["id"] == "person:" + pid for node in nodes):
                    edges.append({"id": "agent-rel:" + str(rel["relationship_id"]), "from": "person:" + pid,
                                  "to": "agent:" + aid, "kind": rel.get("relationship_role")})
                if len(nodes) >= budget:
                    break
    if focus and normalized_mode == "ANOMALIES":
        anomalies = list_anomalies(actor, organization_id=focus, limit=max(1, remaining))
        focus_row = next(
            (item for item in organizations if str(item.get("organization_id")) == focus),
            roots[0] if roots else {},
        )
        nodes, edges = _anomaly_graph(
            anomalies, focus, str(focus_row.get("organization_name") or focus)
        )
    nodes.sort(key=lambda item: (str(item.get("kind")), int(item.get("sort_order") or 0),
                                 str(item.get("label")), str(item["id"])))
    edges.sort(key=lambda item: (str(item.get("kind")), str(item["from"]), str(item["to"]), str(item["id"])))
    return {"focus_id": focus, "mode": normalized_mode, "layout": "HIERARCHICAL", "depth": bounded_depth,
            "nodes": nodes, "edges": edges, "anomalies": anomalies, "truncated": len(nodes) >= budget}


def _current_version(executor: Any = None, *, lock: bool = False) -> Dict[str, Any]:
    executor = executor or connection
    query_one = getattr(executor, "query_one", None) or executor.execute_query_one
    row = _row(query_one(
        "SELECT VERSION_ID, VERSION_NUMBER FROM CX_ORGANIZATION_VERSIONS "
        "WHERE VERSION_NUMBER = (SELECT MAX(VERSION_NUMBER) FROM CX_ORGANIZATION_VERSIONS)" +
        (" FOR UPDATE" if lock else "")
    ))
    if not row:
        raise OrganizationError("organization version is unavailable")
    return {"version_id": str(row["version_id"]), "version_number": int(row.get("version_number") or 0)}


def create_change_set(actor_principal_id: str, reason: str, idempotency_key: str, *, scheduled_at: Any = None) -> Dict[str, Any]:
    _access(actor_principal_id, CREATE_ACTION)
    reason = _text(reason, "reason", 2000, required=True)
    idempotency_key = _text(idempotency_key, "idempotency_key", 256, required=True)
    existing = _query_one(
        "SELECT CHANGE_SET_ID, STATUS, BASE_VERSION_ID, REASON, RISK_LEVEL FROM CX_ORG_CHANGESETS "
        "WHERE AUTHOR_PRINCIPAL_ID = :author_principal_id AND IDEMPOTENCY_KEY = :idempotency_key",
        {"author_principal_id": actor_principal_id, "idempotency_key": idempotency_key},
    )
    if existing:
        if str(existing.get("reason") or "") != reason:
            raise OrganizationConflict("idempotency key was already used")
        return {"change_id": existing["change_set_id"], "status": existing.get("status"),
                "base_version_id": existing.get("base_version_id"),
                "risk_level": existing.get("risk_level"), "reason": existing.get("reason"), "idempotent": True}
    change_id = _id("OCS")
    base_version = _current_version()
    connection.execute(
        "INSERT INTO CX_ORG_CHANGESETS(CHANGE_SET_ID, STATUS, BASE_VERSION_ID, AUTHOR_PRINCIPAL_ID, REASON, "
        "IDEMPOTENCY_KEY, RISK_LEVEL, SCHEDULED_FOR, ROW_VERSION) VALUES (:change_set_id, 'DRAFT', "
        ":base_version_id, :author_principal_id, :reason, :idempotency_key, 'LOW', :scheduled_for, 1)",
        {"change_set_id": change_id, "base_version_id": base_version["version_id"],
         "author_principal_id": actor_principal_id, "reason": reason,
         "idempotency_key": idempotency_key, "scheduled_for": scheduled_at},
    )
    identity_api._audit(actor_principal_id, "ORG_CHANGESET_CREATE", "ORG_CHANGESET", change_id, "ALLOW", reason)
    return {"change_id": change_id, "status": "DRAFT", "base_version_id": base_version["version_id"],
            "base_version_number": base_version["version_number"], "risk_level": "LOW",
            "reason": reason, "idempotency_key": idempotency_key, "idempotent": False}


def _change_for_actor(change_id: str, actor: str, *, lock: bool = False, executor: Any = None) -> Dict[str, Any]:
    executor = executor or connection
    query_one = getattr(executor, "query_one", None) or executor.execute_query_one
    row = _row(query_one(
        "SELECT CHANGE_SET_ID, STATUS, BASE_VERSION_ID, AUTHOR_PRINCIPAL_ID, REASON, RISK_LEVEL, "
        "SCHEDULED_FOR, ROW_VERSION FROM CX_ORG_CHANGESETS WHERE CHANGE_SET_ID = :change_id" +
        (" FOR UPDATE" if lock else ""),
        {"change_id": _text(change_id, "change_id", 256, required=True)},
    ))
    if not row or (str(row.get("author_principal_id")) != actor and identity_api.effective_access(actor, "organizations.changes.read.all").get("decision") != "ALLOW"):
        raise OrganizationError("organization change is unavailable")
    return row


def _change_for_decision(change_id: str, actor: str, *, executor: Any) -> Dict[str, Any]:
    """Load a submitted change only after the caller's approval authority is checked."""
    access = _access(actor, APPROVE_ACTION)
    row = _row(executor.query_one(
        "SELECT CHANGE_SET_ID, STATUS, BASE_VERSION_ID, AUTHOR_PRINCIPAL_ID, REASON, RISK_LEVEL, "
        "SCHEDULED_FOR, ROW_VERSION FROM CX_ORG_CHANGESETS WHERE CHANGE_SET_ID = :change_id FOR UPDATE",
        {"change_id": _text(change_id, "change_id", 256, required=True)},
    ))
    if not row:
        raise OrganizationError("organization change is unavailable")
    if "ALL" not in {str(item).upper() for item in access.get("scopes", [])}:
        for item in _operations(change_id, executor):
            payload = item.get("payload") or {}
            target_type = str(item.get("target_type") or "ORGANIZATION").upper()
            organization_id = ""
            if str(item.get("operation_type") or "") == "CREATE_ORGANIZATION":
                organization_id = str(payload.get("parent_id") or "")
            elif target_type == "ORGANIZATION":
                organization_id = str(item.get("target_id") or "")
            elif target_type == "MEMBERSHIP":
                organization_id = str(payload.get("organization_id") or "")
                if not organization_id:
                    existing = _row(executor.query_one(
                        "SELECT ORGANIZATION_ID FROM CX_ORGANIZATION_MEMBERS WHERE MEMBERSHIP_ID = :target_id",
                        {"target_id": item.get("target_id")},
                    )) or {}
                    organization_id = str(existing.get("organization_id") or "")
            elif target_type == "REPORTING":
                principal_id = str(payload.get("principal_id") or "")
                if not principal_id:
                    existing = _operation_snapshot_tx(executor, item)
                    principal_id = str(existing.get("principal_id") or "")
                membership = _row(executor.query_one(
                    "SELECT ORGANIZATION_ID FROM CX_ORGANIZATION_MEMBERS WHERE PRINCIPAL_ID = :principal_id "
                    "AND MEMBERSHIP_KIND = 'PRIMARY' AND STATUS = 'ACTIVE' " + _limit("one_row"),
                    {"principal_id": principal_id, "one_row": 1},
                )) or {}
                organization_id = str(membership.get("organization_id") or "")
            elif target_type == "AGENT_RELATIONSHIP":
                organization_id = str(payload.get("responsible_organization_id") or "")
                if not organization_id:
                    existing = _operation_snapshot_tx(executor, item)
                    organization_id = str(existing.get("responsible_organization_id") or "")
            if not organization_id or not _visible_organization(actor, organization_id, APPROVE_ACTION):
                raise PermissionError("organization approval target is outside the approver scope")
    return row


def _operations(change_id: str, executor: Any = None) -> List[Dict[str, Any]]:
    executor = executor or connection
    query = getattr(executor, "query", None) or executor.execute_query
    rows = _rows(query(
        "SELECT OPERATION_ID, CHANGE_SET_ID, SEQUENCE_NUMBER, OPERATION_TYPE, TARGET_TYPE, TARGET_ID, "
        "EXPECTED_ROW_VERSION, COMMAND_JSON, BEFORE_DIGEST, AFTER_DIGEST, STATUS, CREATED_AT "
        "FROM CX_ORG_CHANGE_OPERATIONS WHERE CHANGE_SET_ID = :change_id AND STATUS = 'ACTIVE' "
        "ORDER BY SEQUENCE_NUMBER, OPERATION_ID",
        {"change_id": change_id},
    ))
    for row in rows:
        row["payload"] = _load_json(row.pop("command_json", "{}"), {})
        row["expected_version"] = row.pop("expected_row_version", None)
        row["sequence_no"] = row.pop("sequence_number", None)
    return rows


def _canonical_operation(operation_type: str, target_id: str, payload: Mapping[str, Any], expected_version: Optional[int]) -> Dict[str, Any]:
    operation = str(operation_type or "").upper()
    if operation not in OPERATION_TYPES:
        raise OrganizationError("organization operation is invalid")
    target = _text(target_id, "target_id", 256, required=operation != "CREATE_ORGANIZATION")
    clean = dict(payload or {})
    allowed = {
        "CREATE_ORGANIZATION": {"organization_id", "parent_id", "organization_code", "organization_name", "organization_type", "is_legal_entity", "sort_order", "responsible_principal_id", "security_domain_id", "source_type"},
        "RENAME_ORGANIZATION": {"organization_name"},
        "UPDATE_ORGANIZATION": {"organization_code", "organization_type", "sort_order", "responsible_principal_id", "security_domain_id"},
        "MOVE_ORGANIZATION": {"parent_id"},
        "RETIRE_ORGANIZATION": {"reason"},
        "ADD_MEMBERSHIP": {"membership_id", "organization_id", "principal_id", "membership_kind", "membership_role", "valid_from", "valid_until", "source_type"},
        "END_MEMBERSHIP": {"membership_id", "principal_id", "membership_kind"},
        "SET_REPORTING": {"relationship_id", "principal_id", "manager_principal_id", "relationship_type", "valid_from", "valid_until", "source_type"},
        "END_REPORTING": {"relationship_id"},
        "SET_AGENT_RELATIONSHIP": {"relationship_id", "agent_id", "principal_id", "relationship_role", "responsible_group_id", "responsible_organization_id"},
        "END_AGENT_RELATIONSHIP": {"relationship_id", "agent_id", "principal_id", "relationship_role"},
    }[operation]
    unknown = set(clean) - allowed
    if unknown:
        raise OrganizationError("organization operation contains unsupported fields")
    if operation == "CREATE_ORGANIZATION":
        clean["organization_id"] = _text(clean.get("organization_id") or _id("ORG"), "organization_id", 256, required=True)
        clean["organization_name"] = _text(clean.get("organization_name"), "organization_name", 256, required=True)
        clean["organization_code"] = _text(clean.get("organization_code"), "organization_code", 128, required=True)
        clean["organization_type"] = _text(clean.get("organization_type") or "DEPARTMENT", "organization_type", 64, required=True).upper()
        target = clean["organization_id"]
    if operation == "RENAME_ORGANIZATION":
        clean["organization_name"] = _text(clean.get("organization_name"), "organization_name", 256, required=True)
    if operation in {"ADD_MEMBERSHIP", "END_MEMBERSHIP"} and "membership_kind" in clean:
        clean["membership_kind"] = str(clean["membership_kind"]).upper()
        if clean["membership_kind"] not in MEMBERSHIP_KINDS:
            raise OrganizationError("membership kind is invalid")
    if operation == "SET_REPORTING":
        clean["relationship_type"] = str(clean.get("relationship_type") or "").upper()
        if clean["relationship_type"] not in REPORTING_TYPES:
            raise OrganizationError("reporting type is invalid")
    if operation in {"SET_AGENT_RELATIONSHIP", "END_AGENT_RELATIONSHIP"}:
        clean["relationship_role"] = str(clean.get("relationship_role") or "").upper()
        if clean["relationship_role"] not in AGENT_ROLES:
            raise OrganizationError("Agent relationship role is invalid")
    if expected_version is not None and int(expected_version) < 0:
        raise OrganizationError("expected version is invalid")
    return {"operation_type": operation, "target_id": target, "payload": clean,
            "expected_version": int(expected_version) if expected_version is not None else None}


def _risk_for(operations: Sequence[Mapping[str, Any]]) -> str:
    for item in operations:
        kind = str(item.get("operation_type") or "").upper()
        payload = item.get("payload") or {}
        if kind not in LOW_RISK_OPERATIONS:
            return "HIGH"
        if kind in {"ADD_MEMBERSHIP", "END_MEMBERSHIP"} and str(payload.get("membership_kind") or "").upper() != "SECONDARY":
            return "HIGH"
        if kind == "UPDATE_ORGANIZATION" and payload.get("security_domain_id") is not None:
            return "HIGH"
    return "LOW"


def append_operation(
    actor_principal_id: str,
    change_id: str,
    operation_type: str,
    target_type: str,
    target_id: str,
    command: Mapping[str, Any],
    expected_row_version: Optional[int] = None,
) -> Dict[str, Any]:
    _access(actor_principal_id, CHANGE_ACTION)
    change = _change_for_actor(change_id, actor_principal_id)
    if str(change.get("status") or "").upper() != "DRAFT":
        raise OrganizationConflict("organization change is not editable")
    normalized_target_type = str(target_type or "").upper()
    if normalized_target_type not in {"ORGANIZATION", "MEMBERSHIP", "REPORTING", "AGENT_RELATIONSHIP"}:
        raise OrganizationError("operation target type is invalid")
    auto_organization_id = (
        str(operation_type or "").upper() == "CREATE_ORGANIZATION"
        and not str((command or {}).get("organization_id") or "").strip()
    )
    operation = _canonical_operation(operation_type, target_id, command, expected_row_version)
    operation["target_type"] = normalized_target_type
    existing = _operations(change_id)
    if operation["operation_type"] == "CREATE_ORGANIZATION":
        if normalized_target_type != "ORGANIZATION":
            raise OrganizationError("operation target type is invalid")
        pending_ids = {
            str((item.get("payload") or {}).get("organization_id") or item.get("target_id") or "")
            for item in existing
            if str(item.get("operation_type") or "").upper() == "CREATE_ORGANIZATION"
        }
        organization_id = str(operation["payload"]["organization_id"])
        for _ in range(5):
            persisted = _query_one(
                "SELECT ORGANIZATION_ID FROM CX_ORGANIZATIONS WHERE ORGANIZATION_ID = :organization_id",
                {"organization_id": organization_id},
            )
            if not persisted and organization_id not in pending_ids:
                break
            if not auto_organization_id:
                raise OrganizationConflict("organization ID already exists")
            organization_id = _id("ORG")
            operation["payload"]["organization_id"] = organization_id
            operation["target_id"] = organization_id
        else:
            raise OrganizationConflict("unique organization ID could not be generated")
        parent_id = str(operation["payload"].get("parent_id") or "")
        if parent_id and parent_id == organization_id:
            raise OrganizationError("organization cannot be its own parent")
        if parent_id:
            _require_visible(actor_principal_id, parent_id, CHANGE_ACTION)
    elif normalized_target_type == "ORGANIZATION":
        _require_visible(actor_principal_id, operation["target_id"], CHANGE_ACTION)
    elif normalized_target_type == "MEMBERSHIP":
        organization_id = str(operation["payload"].get("organization_id") or "")
        if not organization_id:
            existing_membership = _query_one(
                "SELECT ORGANIZATION_ID FROM CX_ORGANIZATION_MEMBERS WHERE MEMBERSHIP_ID = :membership_id",
                {"membership_id": operation["target_id"]},
            )
            organization_id = str((existing_membership or {}).get("organization_id") or "")
        _require_visible(actor_principal_id, organization_id, CHANGE_ACTION)
        principal_id = str(operation["payload"].get("principal_id") or "")
        if principal_id and not identity_api._principal_visible_to(actor_principal_id, principal_id):
            raise OrganizationError("operation target is unavailable")
        if principal_id and identity_api._protected_bootstrap_admin(principal_id):
            raise OrganizationError("bootstrap administrator cannot be an organization person")
        if principal_id and not identity_api.has_active_login_identity(principal_id):
            raise OrganizationError("organization person requires an active login account")
    elif normalized_target_type == "REPORTING":
        for field in ("principal_id", "manager_principal_id"):
            principal_id = str(operation["payload"].get(field) or "")
            if principal_id and not identity_api._principal_visible_to(actor_principal_id, principal_id):
                raise OrganizationError("operation target is unavailable")
    elif normalized_target_type == "AGENT_RELATIONSHIP":
        agent_id = str(operation["payload"].get("agent_id") or "")
        if not agent_id or not identity_api._agent_visible_to(actor_principal_id, agent_id):
            raise OrganizationError("operation target is unavailable")
    if len(existing) >= MAX_DRAFT_OPERATIONS:
        raise OrganizationError("organization change operation limit exceeded")
    operation_id = _id("OCO")
    sequence = len(existing) + 1
    operation["operation_id"] = operation_id
    operation["sequence_no"] = sequence
    risk = _risk_for([*existing, operation])
    connection.execute(
        "INSERT INTO CX_ORG_CHANGE_OPERATIONS(OPERATION_ID, CHANGE_SET_ID, SEQUENCE_NUMBER, OPERATION_TYPE, TARGET_ID, "
        "TARGET_TYPE, EXPECTED_ROW_VERSION, COMMAND_JSON, BEFORE_DIGEST, AFTER_DIGEST, STATUS) "
        "VALUES (:operation_id, :change_set_id, :sequence_number, :operation_type, :target_id, :target_type, "
        ":expected_row_version, :command_json, :before_digest, :after_digest, 'ACTIVE')",
        {"operation_id": operation_id, "change_set_id": change_id, "sequence_number": sequence,
         "operation_type": operation["operation_type"], "target_id": operation["target_id"],
         "target_type": normalized_target_type,
         "expected_row_version": operation["expected_version"], "command_json": _json(operation["payload"]),
         "before_digest": None, "after_digest": _digest(operation["payload"])},
    )
    connection.execute(
        "UPDATE CX_ORG_CHANGESETS SET RISK_LEVEL = :risk_level, ROW_VERSION = ROW_VERSION + 1, "
        "UPDATED_AT = CURRENT_TIMESTAMP WHERE CHANGE_SET_ID = :change_id AND STATUS = 'DRAFT'",
        {"risk_level": risk, "change_id": change_id},
    )
    return {**operation, "risk_level": risk}


def _proposed_parents(operations: Sequence[Mapping[str, Any]], executor: Any = None) -> tuple[Dict[str, Optional[str]], Dict[str, int]]:
    executor = executor or connection
    query = getattr(executor, "query", None) or executor.execute_query
    rows = _rows(query(
        "SELECT ORGANIZATION_ID, PARENT_ID, ROW_VERSION FROM CX_ORGANIZATIONS WHERE STATUS <> 'DELETED'"
    ))
    parents: Dict[str, Optional[str]] = {str(row["organization_id"]): (str(row["parent_id"]) if row.get("parent_id") is not None else None) for row in rows}
    versions = {str(row["organization_id"]): int(row.get("row_version") or 0) for row in rows}
    for item in operations:
        kind, payload = str(item["operation_type"]), item.get("payload") or {}
        target = str(item.get("target_id") or "")
        if kind == "CREATE_ORGANIZATION":
            if target in parents:
                raise OrganizationConflict("organization ID already exists")
            parent = payload.get("parent_id")
            parents[target] = str(parent) if parent else None
            versions[target] = 0
        elif kind == "MOVE_ORGANIZATION":
            parents[target] = str(payload.get("parent_id")) if payload.get("parent_id") else None
    return parents, versions


def _cycle_nodes(parents: Mapping[str, Optional[str]]) -> List[str]:
    cycle: set[str] = set()
    complete: set[str] = set()
    for start in parents:
        if start in complete:
            continue
        path: List[str] = []
        positions: Dict[str, int] = {}
        current: Optional[str] = start
        while current is not None and current in parents and current not in complete:
            if current in positions:
                cycle.update(path[positions[current]:])
                break
            positions[current] = len(path)
            path.append(current)
            current = parents.get(current)
        complete.update(path)
    return sorted(cycle)


def validate_change_set(actor_principal_id: str, change_id: str) -> Dict[str, Any]:
    _access(actor_principal_id, CHANGE_ACTION)
    change = _change_for_actor(change_id, actor_principal_id)
    operations = _operations(change_id)
    errors: List[Dict[str, Any]] = []
    if not operations:
        errors.append({"code": "EMPTY_CHANGESET", "message": "at least one operation is required"})
    try:
        parents, versions = _proposed_parents(operations)
    except OrganizationConflict as exc:
        parents, versions = {}, {}
        errors.append({"code": "DUPLICATE_ORGANIZATION", "message": str(exc)})
    missing = sorted({parent for parent in parents.values() if parent and parent not in parents})
    if missing:
        errors.append({"code": "MISSING_PARENT", "message": "a proposed parent is unavailable", "count": len(missing)})
    cycles = _cycle_nodes(parents)
    if cycles:
        errors.append({"code": "ORGANIZATION_CYCLE", "message": "organization hierarchy contains a cycle", "subject_ids": cycles[:20]})
    stale: List[str] = []
    for item in operations:
        expected = item.get("expected_version")
        target = str(item.get("target_id") or "")
        if expected is not None and target in versions and int(expected) != int(versions[target]):
            stale.append(target)
    if str(change.get("base_version_id") or "") != _current_version()["version_id"]:
        errors.append({"code": "STALE_BASE_VERSION", "message": "organization version changed"})
    if stale:
        errors.append({"code": "STALE_ROW_VERSION", "message": "organization rows changed", "subject_ids": sorted(set(stale))[:20]})
    # Validate operation targets and authority again; a draft never carries authorization.
    for item in operations:
        if item["operation_type"] == "CREATE_ORGANIZATION":
            parent = str((item.get("payload") or {}).get("parent_id") or "")
            if parent and not _visible_organization(actor_principal_id, parent, CHANGE_ACTION):
                errors.append({"code": "SCOPE_DENIED", "message": "operation target is unavailable"})
        elif str(item.get("target_type") or "ORGANIZATION").upper() == "ORGANIZATION" and not _visible_organization(actor_principal_id, str(item["target_id"]), CHANGE_ACTION):
            errors.append({"code": "SCOPE_DENIED", "message": "operation target is unavailable"})
    risk = _risk_for(operations)
    valid = not errors
    connection.execute(
        "UPDATE CX_ORG_CHANGESETS SET STATUS = :status, RISK_LEVEL = :risk_level, VALIDATION_JSON = :validation_json, "
        "ROW_VERSION = ROW_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE CHANGE_SET_ID = :change_id AND STATUS IN ('DRAFT','VALIDATED')",
        {"status": "VALIDATED" if valid else "DRAFT", "risk_level": risk,
         "validation_json": _json({"valid": valid, "errors": errors}), "change_id": change_id},
    )
    return {"change_id": change_id, "valid": valid, "risk_level": risk, "requires_approval": risk != "LOW", "errors": errors}


def calculate_impact(actor_principal_id: str, change_id: str) -> Dict[str, Any]:
    _access(actor_principal_id, CHANGE_ACTION)
    _change_for_actor(change_id, actor_principal_id)
    operations = _operations(change_id)
    organization_ids = sorted({str(item.get("target_id") or "") for item in operations if str(item.get("target_id") or "")})
    principal_ids = sorted({str((item.get("payload") or {}).get("principal_id") or "") for item in operations if (item.get("payload") or {}).get("principal_id")})
    agent_ids = sorted({str((item.get("payload") or {}).get("agent_id") or "") for item in operations if (item.get("payload") or {}).get("agent_id")})
    subtree_count = 0
    for oid in organization_ids:
        if _visible_organization(actor_principal_id, oid, CHANGE_ACTION):
            row = _query_one(
                "SELECT COUNT(*) AS CNT FROM CX_ORGANIZATION_CLOSURE WHERE ANCESTOR_ID = :organization_id",
                {"organization_id": oid},
            )
            subtree_count += int((row or {}).get("cnt") or 0)
    risk = _risk_for(operations)
    impact = {"change_id": change_id, "risk_level": risk, "operation_count": len(operations),
              "organization_count": len(organization_ids), "visible_subtree_node_count": subtree_count,
              "principal_ids": principal_ids[:500], "agent_ids": agent_ids[:500],
              "permission_invalidation_required": bool(principal_ids),
              "agent_disposition_required": any(item["operation_type"] in {"MOVE_ORGANIZATION", "RETIRE_ORGANIZATION", "SET_AGENT_RELATIONSHIP", "END_AGENT_RELATIONSHIP"} for item in operations),
              "asynchronous_recommended": len(operations) > 100 or subtree_count > 5000}
    connection.execute(
        "UPDATE CX_ORG_CHANGESETS SET IMPACT_JSON = :impact_json, RISK_LEVEL = :risk_level, "
        "UPDATED_AT = CURRENT_TIMESTAMP WHERE CHANGE_SET_ID = :change_id",
        {"impact_json": _json(impact), "risk_level": risk, "change_id": change_id},
    )
    return impact


def undo_operation(actor_principal_id: str, change_id: str) -> Dict[str, Any]:
    """Deactivate the last active semantic operation in an editable draft."""
    _access(actor_principal_id, CHANGE_ACTION)
    change = _change_for_actor(change_id, actor_principal_id)
    if str(change.get("status") or "").upper() != "DRAFT":
        raise OrganizationConflict("organization change is not editable")
    operation = _query_one(
        "SELECT OPERATION_ID FROM CX_ORG_CHANGE_OPERATIONS WHERE CHANGE_SET_ID = :change_id "
        "AND STATUS = 'ACTIVE' ORDER BY SEQUENCE_NUMBER DESC " + _limit("one_row"),
        {"change_id": change_id, "one_row": 1},
    )
    if operation:
        connection.execute(
            "UPDATE CX_ORG_CHANGE_OPERATIONS SET STATUS = 'UNDONE' WHERE OPERATION_ID = :operation_id "
            "AND STATUS = 'ACTIVE'",
            {"operation_id": operation["operation_id"]},
        )
    return get_change_set(actor_principal_id, change_id)


def redo_operation(actor_principal_id: str, change_id: str) -> Dict[str, Any]:
    """Reactivate the earliest undone operation after the active draft tail."""
    _access(actor_principal_id, CHANGE_ACTION)
    change = _change_for_actor(change_id, actor_principal_id)
    if str(change.get("status") or "").upper() != "DRAFT":
        raise OrganizationConflict("organization change is not editable")
    operation = _query_one(
        "SELECT OPERATION_ID FROM CX_ORG_CHANGE_OPERATIONS WHERE CHANGE_SET_ID = :change_id "
        "AND STATUS = 'UNDONE' ORDER BY SEQUENCE_NUMBER ASC " + _limit("one_row"),
        {"change_id": change_id, "one_row": 1},
    )
    if operation:
        connection.execute(
            "UPDATE CX_ORG_CHANGE_OPERATIONS SET STATUS = 'ACTIVE' WHERE OPERATION_ID = :operation_id "
            "AND STATUS = 'UNDONE'",
            {"operation_id": operation["operation_id"]},
        )
    return get_change_set(actor_principal_id, change_id)


def cancel_change_set(actor_principal_id: str, change_id: str, reason: str) -> Dict[str, Any]:
    """Cancel an unpublished draft while retaining its operations as audit evidence."""
    _access(actor_principal_id, CHANGE_ACTION)
    change = _change_for_actor(change_id, actor_principal_id)
    if (
        str(change.get("author_principal_id") or "") != actor_principal_id
        and not identity_api._protected_bootstrap_admin(actor_principal_id)
    ):
        raise PermissionError("only the organization requester can cancel this change")
    status = str(change.get("status") or "").upper()
    if status not in {"DRAFT", "VALIDATED"}:
        raise OrganizationConflict("organization change cannot be cancelled")
    clean_reason = _text(reason, "reason", 2000, required=True)
    changed = connection.execute(
        "UPDATE CX_ORG_CHANGESETS SET STATUS = 'CANCELLED', OUTCOME_JSON = :outcome_json, "
        "ROW_VERSION = ROW_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE CHANGE_SET_ID = :change_id AND STATUS IN ('DRAFT','VALIDATED')",
        {
            "change_id": change_id,
            "outcome_json": _json({"cancelled_by": actor_principal_id, "reason": clean_reason}),
        },
    )
    if changed != 1:
        raise OrganizationConflict("organization change was updated concurrently")
    identity_api._audit(
        actor_principal_id,
        "ORG_CHANGESET_CANCEL",
        "ORG_CHANGESET",
        change_id,
        "ALLOW",
        clean_reason,
    )
    return get_change_set(actor_principal_id, change_id)


def submit_change_set(actor_principal_id: str, change_id: str) -> Dict[str, Any]:
    """Submit a change, or publish low-risk changes directly in Community."""
    _access(actor_principal_id, SUBMIT_ACTION)
    if not _approvals_enabled():
        change = _change_for_actor(change_id, actor_principal_id)
        if str(change.get("status") or "").upper() != "VALIDATED":
            raise OrganizationConflict("organization change must be validated before submission")
        return publish_low_risk(
            actor_principal_id, change_id,
            "Community edition direct publication of validated low-risk organization change",
        )
    approval_id = _id("APR")

    def work(tx: Any) -> Dict[str, Any]:
        change = _change_for_actor(change_id, actor_principal_id, lock=True, executor=tx)
        status = str(change.get("status") or "").upper()
        if status == "PENDING_APPROVAL":
            existing = _row(tx.query_one(
                "SELECT APPROVAL_ID FROM APPROVAL_REQUESTS WHERE ENTITY_TYPE = 'ORGANIZATION_CHANGE' "
                "AND ENTITY_ID = :change_id AND APPROVAL_STATUS = 'PENDING' ORDER BY CREATED_AT DESC " + _limit("one_row"),
                {"change_id": change_id, "one_row": 1},
            ))
            if not existing:
                raise OrganizationConflict("organization approval request is missing")
            return {"change_id": change_id, "status": status, "approval_id": existing["approval_id"], "idempotent": True}
        if status != "VALIDATED":
            raise OrganizationConflict("organization change must be validated before submission")
        operations = _operations(change_id, tx)
        if not operations:
            raise OrganizationConflict("organization change has no operations")
        current = _current_version(tx, lock=True)
        if str(change.get("base_version_id") or "") != current["version_id"]:
            raise OrganizationConflict("organization version changed")
        changed = tx.execute(
            "UPDATE CX_ORG_CHANGESETS SET STATUS = 'PENDING_APPROVAL', SUBMITTED_AT = CURRENT_TIMESTAMP, "
            "ROW_VERSION = ROW_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE CHANGE_SET_ID = :change_id AND STATUS = 'VALIDATED'",
            {"change_id": change_id},
        )
        if changed != 1:
            raise OrganizationConflict("organization change was submitted concurrently")
        tx.execute(
            "INSERT INTO APPROVAL_REQUESTS(APPROVAL_ID, ENTITY_TYPE, ENTITY_ID, REQUESTED_BY) "
            "VALUES (:approval_id, 'ORGANIZATION_CHANGE', :change_id, :requested_by)",
            {"approval_id": approval_id, "change_id": change_id, "requested_by": actor_principal_id},
        )
        identity_api._audit_tx(tx, actor_principal_id, "ORG_CHANGESET_SUBMIT", "ORG_CHANGESET", change_id, "ALLOW", str(change.get("reason") or "approval requested"))
        return {"change_id": change_id, "status": "PENDING_APPROVAL", "approval_id": approval_id, "idempotent": False}

    submitted = connection.execute_transaction_callback(work)
    result = get_change_set(actor_principal_id, change_id)
    result.update({key: submitted[key] for key in ("approval_id", "idempotent")})
    return result


def withdraw_change_set(actor_principal_id: str, change_id: str, reason: str) -> Dict[str, Any]:
    """Withdraw the author's pending request and restore its validated snapshot."""
    _access(actor_principal_id, SUBMIT_ACTION)
    reason = _text(reason, "reason", 500, required=True)

    def work(tx: Any) -> Dict[str, Any]:
        change = _change_for_actor(change_id, actor_principal_id, lock=True, executor=tx)
        if str(change.get("author_principal_id") or "") != actor_principal_id:
            raise PermissionError("only the organization requester can withdraw their change")
        if str(change.get("status") or "").upper() != "PENDING_APPROVAL":
            raise OrganizationConflict("organization change is not awaiting approval")
        request = _row(tx.query_one(
            "SELECT APPROVAL_ID, APPROVAL_STATUS FROM APPROVAL_REQUESTS "
            "WHERE ENTITY_TYPE = 'ORGANIZATION_CHANGE' AND ENTITY_ID = :change_id "
            "AND APPROVAL_STATUS = 'PENDING' FOR UPDATE",
            {"change_id": change_id},
        ))
        approval_id = str((request or {}).get("approval_id") or "")
        decided = 1
        if request:
            withdrawn_reason = "WITHDRAWN: " + reason
            decided = tx.execute(
                "UPDATE APPROVAL_REQUESTS SET APPROVAL_STATUS = 'REJECTED', APPROVED_BY = NULL, "
                "APPROVED_AT = CURRENT_TIMESTAMP, REJECT_REASON = :reason WHERE APPROVAL_ID = :approval_id "
                "AND APPROVAL_STATUS = 'PENDING'",
                {"reason": withdrawn_reason, "approval_id": approval_id},
            )
        changed = tx.execute(
            "UPDATE CX_ORG_CHANGESETS SET STATUS = 'VALIDATED', SUBMITTED_AT = NULL, OUTCOME_JSON = NULL, "
            "ROW_VERSION = ROW_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE CHANGE_SET_ID = :change_id AND STATUS = 'PENDING_APPROVAL'",
            {"change_id": change_id},
        )
        if decided != 1 or changed != 1:
            raise OrganizationConflict("organization withdrawal was decided concurrently")
        identity_api._audit_tx(
            tx, actor_principal_id,
            "ORG_CHANGESET_WITHDRAW" if request else "ORG_CHANGESET_WITHDRAW_ORPHAN_RECOVERY",
            "ORG_CHANGESET",
            change_id, "ALLOW", reason,
        )
        return {"approval_id": approval_id or None, "change_id": change_id, "status": "VALIDATED",
                "orphan_recovered": not bool(request)}

    withdrawn = connection.execute_transaction_callback(work)
    result = get_change_set(actor_principal_id, change_id)
    result["withdrawn_approval_id"] = withdrawn["approval_id"]
    result["orphan_recovered"] = withdrawn["orphan_recovered"]
    return result


def _snapshot_tx(tx: Any, organization_id: str) -> Dict[str, Any]:
    return _row(tx.query_one(
        "SELECT ORGANIZATION_ID, PARENT_ID, ORGANIZATION_CODE, ORGANIZATION_NAME, ORGANIZATION_TYPE, "
        "IS_LEGAL_ENTITY, SORT_ORDER, RESPONSIBLE_PRINCIPAL_ID, SECURITY_DOMAIN_ID, VALID_FROM, VALID_UNTIL, "
        "SOURCE_TYPE, SOURCE_CONNECTOR_ID, EXTERNAL_OBJECT_ID, STATUS, ROW_VERSION "
        "FROM CX_ORGANIZATIONS WHERE ORGANIZATION_ID = :organization_id",
        {"organization_id": organization_id},
    )) or {}


def _operation_snapshot_tx(tx: Any, item: Mapping[str, Any]) -> Dict[str, Any]:
    target_type = str(item.get("target_type") or "ORGANIZATION").upper()
    target = str(item.get("target_id") or "")
    payload = item.get("payload") or {}
    if target_type == "ORGANIZATION":
        return _snapshot_tx(tx, target)
    if target_type == "MEMBERSHIP":
        membership_id = str(payload.get("membership_id") or target)
        return _row(tx.query_one(
            "SELECT MEMBERSHIP_ID, ORGANIZATION_ID, PRINCIPAL_ID, MEMBERSHIP_KIND, MEMBERSHIP_ROLE, "
            "VALID_FROM, VALID_UNTIL, SOURCE_TYPE, STATUS, ROW_VERSION FROM CX_ORGANIZATION_MEMBERS "
            "WHERE MEMBERSHIP_ID = :membership_id",
            {"membership_id": membership_id},
        )) or {}
    if target_type == "REPORTING":
        relationship_id = str(payload.get("relationship_id") or target)
        return _row(tx.query_one(
            "SELECT RELATIONSHIP_ID, PRINCIPAL_ID, MANAGER_PRINCIPAL_ID, RELATIONSHIP_TYPE, VALID_FROM, "
            "VALID_UNTIL, SOURCE_TYPE, STATUS, ROW_VERSION FROM CX_REPORTING_RELATIONSHIPS "
            "WHERE RELATIONSHIP_ID = :relationship_id",
            {"relationship_id": relationship_id},
        )) or {}
    if target_type == "AGENT_RELATIONSHIP":
        relationship_id = str(payload.get("relationship_id") or target)
        return _row(tx.query_one(
            "SELECT RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, RELATIONSHIP_ROLE, RESPONSIBLE_GROUP_ID, "
            "RESPONSIBLE_ORGANIZATION_ID, STATUS, CREATED_AT, ENDED_AT FROM CX_AGENT_RELATIONSHIPS "
            "WHERE RELATIONSHIP_ID = :relationship_id",
            {"relationship_id": relationship_id},
        )) or {}
    return {}


def _apply_operation_tx(tx: Any, item: Mapping[str, Any], actor: str) -> tuple[Dict[str, Any], Dict[str, Any], List[str], bool, str]:
    kind, target, payload = str(item["operation_type"]), str(item["target_id"]), dict(item.get("payload") or {})
    before = _operation_snapshot_tx(tx, item)
    affected: List[str] = []
    structural = False
    scope_organization_id = target if str(item.get("target_type") or "ORGANIZATION").upper() == "ORGANIZATION" else str(payload.get("organization_id") or before.get("organization_id") or "")
    if kind == "CREATE_ORGANIZATION":
        tx.execute(
            "INSERT INTO CX_ORGANIZATIONS(ORGANIZATION_ID, PARENT_ID, ORGANIZATION_CODE, ORGANIZATION_NAME, "
            "ORGANIZATION_TYPE, IS_LEGAL_ENTITY, SORT_ORDER, RESPONSIBLE_PRINCIPAL_ID, SECURITY_DOMAIN_ID, "
            "SOURCE_TYPE, STATUS, ROW_VERSION, UPDATED_BY) VALUES (:organization_id, :parent_id, "
            ":organization_code, :organization_name, :organization_type, :is_legal_entity, :sort_order, "
            ":responsible_principal_id, :security_domain_id, :source_type, 'ACTIVE', 1, :updated_by)",
            {"organization_id": target, "parent_id": payload.get("parent_id"),
             "organization_code": payload.get("organization_code"), "organization_name": payload.get("organization_name"),
             "organization_type": payload.get("organization_type"),
             "is_legal_entity": bool(payload.get("is_legal_entity")) if _dialect() in {"postgresql", "pg"} else ("Y" if payload.get("is_legal_entity") else "N"),
             "sort_order": int(payload.get("sort_order") or 0), "responsible_principal_id": payload.get("responsible_principal_id"),
             "security_domain_id": payload.get("security_domain_id"), "source_type": payload.get("source_type") or "MANUAL",
             "updated_by": actor},
        )
        structural = True
    elif kind == "RENAME_ORGANIZATION":
        changed = tx.execute(
            "UPDATE CX_ORGANIZATIONS SET ORGANIZATION_NAME = :organization_name, ROW_VERSION = ROW_VERSION + 1, "
            "UPDATED_BY = :updated_by, UPDATED_AT = CURRENT_TIMESTAMP WHERE ORGANIZATION_ID = :organization_id "
            "AND ROW_VERSION = :expected_version AND STATUS <> 'DELETED'",
            {"organization_name": payload["organization_name"], "updated_by": actor, "organization_id": target,
             "expected_version": int(item.get("expected_version") if item.get("expected_version") is not None else before.get("row_version") or 0)},
        )
        if changed != 1:
            raise OrganizationConflict("organization row changed concurrently")
    elif kind == "UPDATE_ORGANIZATION":
        assignments: List[str] = []
        params: Dict[str, Any] = {"organization_id": target, "updated_by": actor,
                                  "expected_version": int(item.get("expected_version") if item.get("expected_version") is not None else before.get("row_version") or 0)}
        columns = {"organization_code": "ORGANIZATION_CODE", "organization_type": "ORGANIZATION_TYPE",
                   "sort_order": "SORT_ORDER", "responsible_principal_id": "RESPONSIBLE_PRINCIPAL_ID",
                   "security_domain_id": "SECURITY_DOMAIN_ID"}
        for field, column in columns.items():
            if field in payload:
                assignments.append(column + " = :" + field)
                params[field] = payload[field]
        if not assignments:
            raise OrganizationError("organization metadata update is empty")
        changed = tx.execute(
            "UPDATE CX_ORGANIZATIONS SET " + ", ".join(assignments) + ", ROW_VERSION = ROW_VERSION + 1, "
            "UPDATED_BY = :updated_by, UPDATED_AT = CURRENT_TIMESTAMP WHERE ORGANIZATION_ID = :organization_id "
            "AND ROW_VERSION = :expected_version AND STATUS <> 'DELETED'", params,
        )
        if changed != 1:
            raise OrganizationConflict("organization row changed concurrently")
    elif kind == "MOVE_ORGANIZATION":
        changed = tx.execute(
            "UPDATE CX_ORGANIZATIONS SET PARENT_ID = :parent_id, ROW_VERSION = ROW_VERSION + 1, "
            "UPDATED_BY = :updated_by, UPDATED_AT = CURRENT_TIMESTAMP WHERE ORGANIZATION_ID = :organization_id "
            "AND ROW_VERSION = :expected_version AND STATUS <> 'DELETED'",
            {"parent_id": payload.get("parent_id"), "updated_by": actor, "organization_id": target,
             "expected_version": int(item.get("expected_version") if item.get("expected_version") is not None else before.get("row_version") or 0)},
        )
        if changed != 1:
            raise OrganizationConflict("organization row changed concurrently")
        structural = True
    elif kind == "RETIRE_ORGANIZATION":
        changed = tx.execute(
            "UPDATE CX_ORGANIZATIONS SET STATUS = 'RETIRED', VALID_UNTIL = CURRENT_TIMESTAMP, "
            "ROW_VERSION = ROW_VERSION + 1, UPDATED_BY = :updated_by, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE ORGANIZATION_ID = :organization_id AND ROW_VERSION = :expected_version AND STATUS = 'ACTIVE'",
            {"updated_by": actor, "organization_id": target,
             "expected_version": int(item.get("expected_version") if item.get("expected_version") is not None else before.get("row_version") or 0)},
        )
        if changed != 1:
            raise OrganizationConflict("organization row changed concurrently")
        structural = True
    elif kind == "ADD_MEMBERSHIP":
        membership_kind = str(payload.get("membership_kind") or "SECONDARY").upper()
        membership_id = str(payload.get("membership_id") or _id("OM"))
        affected.append(_text(payload.get("principal_id"), "principal_id", 256, required=True))
        if membership_kind == "PRIMARY" and tx.query_one(
            "SELECT MEMBERSHIP_ID FROM CX_ORGANIZATION_MEMBERS WHERE PRINCIPAL_ID = :principal_id "
            "AND MEMBERSHIP_KIND = 'PRIMARY' AND STATUS = 'ACTIVE' " + _limit("one_row"),
            {"principal_id": affected[-1], "one_row": 1},
        ):
            raise OrganizationConflict("principal already has an active primary organization")
        tx.execute(
            "INSERT INTO CX_ORGANIZATION_MEMBERS(MEMBERSHIP_ID, ORGANIZATION_ID, PRINCIPAL_ID, MEMBERSHIP_KIND, "
            "MEMBERSHIP_ROLE, VALID_FROM, VALID_UNTIL, SOURCE_TYPE, STATUS, ROW_VERSION) "
            "VALUES (:membership_id, :organization_id, :principal_id, :membership_kind, :membership_role, "
            ":valid_from, :valid_until, :source_type, 'ACTIVE', 1)",
            {"membership_id": membership_id, "organization_id": payload.get("organization_id") or target,
             "principal_id": affected[-1], "membership_kind": membership_kind, "membership_role": payload.get("membership_role"),
             "valid_from": payload.get("valid_from") or identity_api._now(), "valid_until": payload.get("valid_until"),
             "source_type": payload.get("source_type") or "MANUAL"},
        )
    elif kind == "END_MEMBERSHIP":
        membership_kind = str(payload.get("membership_kind") or "SECONDARY").upper()
        affected.append(_text(payload.get("principal_id"), "principal_id", 256, required=True))
        changed = tx.execute(
            "UPDATE CX_ORGANIZATION_MEMBERS SET STATUS = 'ENDED', VALID_UNTIL = CURRENT_TIMESTAMP, "
            "ROW_VERSION = ROW_VERSION + 1 WHERE MEMBERSHIP_ID = :membership_id AND PRINCIPAL_ID = :principal_id "
            "AND MEMBERSHIP_KIND = :membership_kind AND STATUS = 'ACTIVE'",
            {"membership_id": payload.get("membership_id") or target, "principal_id": affected[-1],
             "membership_kind": membership_kind},
        )
        if changed != 1:
            raise OrganizationConflict("organization membership changed concurrently")
    elif kind == "SET_REPORTING":
        relationship_id = str(payload.get("relationship_id") or target)
        affected.extend([_text(payload.get("principal_id"), "principal_id", 256, required=True),
                         _text(payload.get("manager_principal_id"), "manager_principal_id", 256, required=True)])
        tx.execute(
            "INSERT INTO CX_REPORTING_RELATIONSHIPS(RELATIONSHIP_ID, PRINCIPAL_ID, MANAGER_PRINCIPAL_ID, "
            "RELATIONSHIP_TYPE, VALID_FROM, VALID_UNTIL, SOURCE_TYPE, STATUS, ROW_VERSION, UPDATED_BY) "
            "VALUES (:relationship_id, :principal_id, :manager_principal_id, :relationship_type, "
            ":valid_from, :valid_until, :source_type, 'ACTIVE', 1, :updated_by)",
            {"relationship_id": relationship_id, "principal_id": affected[-2], "manager_principal_id": affected[-1],
             "relationship_type": payload.get("relationship_type"), "valid_from": payload.get("valid_from") or identity_api._now(),
             "valid_until": payload.get("valid_until"), "source_type": payload.get("source_type") or "MANUAL",
             "updated_by": actor},
        )
        scope_organization_id = str((_row(tx.query_one(
            "SELECT ORGANIZATION_ID FROM CX_ORGANIZATION_MEMBERS WHERE PRINCIPAL_ID = :principal_id "
            "AND MEMBERSHIP_KIND = 'PRIMARY' AND STATUS = 'ACTIVE' " + _limit("one_row"),
            {"principal_id": affected[-2], "one_row": 1},
        )) or {}).get("organization_id") or "")
    elif kind == "END_REPORTING":
        relationship_id = str(payload.get("relationship_id") or target)
        if before.get("principal_id"):
            affected.append(str(before["principal_id"]))
        changed = tx.execute(
            "UPDATE CX_REPORTING_RELATIONSHIPS SET STATUS = 'ENDED', VALID_UNTIL = CURRENT_TIMESTAMP, "
            "ROW_VERSION = ROW_VERSION + 1, UPDATED_BY = :updated_by, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE RELATIONSHIP_ID = :relationship_id AND STATUS = 'ACTIVE'",
            {"relationship_id": relationship_id, "updated_by": actor},
        )
        if changed != 1:
            raise OrganizationConflict("reporting relationship changed concurrently")
    elif kind == "SET_AGENT_RELATIONSHIP":
        relationship_id = str(payload.get("relationship_id") or target)
        affected.append(_text(payload.get("principal_id"), "principal_id", 256, required=True))
        tx.execute(
            "INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, RELATIONSHIP_ROLE, "
            "RESPONSIBLE_GROUP_ID, RESPONSIBLE_ORGANIZATION_ID, STATUS) VALUES (:relationship_id, :agent_id, "
            ":principal_id, :relationship_role, :responsible_group_id, :responsible_organization_id, 'ACTIVE')",
            {"relationship_id": relationship_id, "agent_id": payload.get("agent_id"), "principal_id": affected[-1],
             "relationship_role": payload.get("relationship_role"), "responsible_group_id": payload.get("responsible_group_id"),
             "responsible_organization_id": payload.get("responsible_organization_id")},
        )
        scope_organization_id = str(payload.get("responsible_organization_id") or "")
    elif kind == "END_AGENT_RELATIONSHIP":
        relationship_id = str(payload.get("relationship_id") or target)
        if before.get("principal_id"):
            affected.append(str(before["principal_id"]))
        changed = tx.execute(
            "UPDATE CX_AGENT_RELATIONSHIPS SET STATUS = 'ENDED', ENDED_AT = CURRENT_TIMESTAMP "
            "WHERE RELATIONSHIP_ID = :relationship_id AND STATUS = 'ACTIVE'",
            {"relationship_id": relationship_id},
        )
        if changed != 1:
            raise OrganizationConflict("Agent relationship changed concurrently")
    else:
        raise OrganizationError("organization operation is unsupported")
    return before, _operation_snapshot_tx(tx, item), affected, structural, scope_organization_id


def _rebuild_closure_tx(tx: Any) -> int:
    rows = _rows(tx.query("SELECT ORGANIZATION_ID, PARENT_ID FROM CX_ORGANIZATIONS WHERE STATUS <> 'DELETED'"))
    parents = {str(row["organization_id"]): (str(row["parent_id"]) if row.get("parent_id") is not None else None) for row in rows}
    cycles = _cycle_nodes(parents)
    if cycles:
        raise OrganizationError("organization hierarchy contains a cycle")
    closure: List[tuple[str, str, int]] = []
    for descendant in sorted(parents):
        closure.append((descendant, descendant, 0))
        ancestor, depth, seen = parents.get(descendant), 1, {descendant}
        while ancestor is not None:
            if ancestor in seen or ancestor not in parents:
                raise OrganizationError("organization hierarchy is invalid")
            closure.append((ancestor, descendant, depth))
            seen.add(ancestor)
            ancestor, depth = parents.get(ancestor), depth + 1
    tx.execute("DELETE FROM CX_ORGANIZATION_CLOSURE")
    for ancestor, descendant, depth in closure:
        tx.execute(
            "INSERT INTO CX_ORGANIZATION_CLOSURE(ANCESTOR_ID, DESCENDANT_ID, DEPTH) "
            "VALUES (:ancestor_id, :descendant_id, :depth)",
            {"ancestor_id": ancestor, "descendant_id": descendant, "depth": depth},
        )
    return len(closure)


def _publish_change(
    actor_principal_id: str,
    change_id: str,
    reason: str,
    *,
    expected_status: str,
    low_risk_only: bool,
    approval_id: str = "",
) -> Dict[str, Any]:
    reason = _text(reason, "reason", 2000, required=True)
    expected_status = str(expected_status).upper()
    if expected_status not in {"VALIDATED", "PENDING_APPROVAL"}:
        raise OrganizationError("organization publication state is invalid")

    def work(tx: Any) -> Dict[str, Any]:
        change = (_change_for_decision(change_id, actor_principal_id, executor=tx) if approval_id
                  else _change_for_actor(change_id, actor_principal_id, lock=True, executor=tx))
        emergency_admin = identity_api._protected_bootstrap_admin(actor_principal_id)
        if (approval_id and str(change.get("author_principal_id") or "") == actor_principal_id
                and not emergency_admin):
            raise PermissionError("organization requester cannot approve their own change")
        if str(change.get("status") or "").upper() != expected_status:
            raise OrganizationConflict("organization change is not ready for publication")
        operations = _operations(change_id, tx)
        if low_risk_only and _risk_for(operations) != "LOW":
            raise OrganizationError("organization change requires approval")
        current_version = _current_version(tx, lock=True)
        if str(change.get("base_version_id") or "") != current_version["version_id"]:
            raise OrganizationConflict("organization version changed")
        moved = tx.execute(
            "UPDATE CX_ORG_CHANGESETS SET STATUS = 'PUBLISHING', ROW_VERSION = ROW_VERSION + 1, "
            "UPDATED_AT = CURRENT_TIMESTAMP WHERE CHANGE_SET_ID = :change_id AND STATUS = :expected_status",
            {"change_id": change_id, "expected_status": expected_status},
        )
        if moved != 1:
            raise OrganizationConflict("organization change was decided concurrently")
        affected: set[str] = set()
        affected_agents: set[str] = set()
        structural = False
        history: List[tuple[Mapping[str, Any], Dict[str, Any], Dict[str, Any], str]] = []
        for item in operations:
            kind = str(item.get("operation_type") or "")
            target_type = str(item.get("target_type") or "ORGANIZATION").upper()
            payload = item.get("payload") or {}
            if target_type == "ORGANIZATION" and kind in {"MOVE_ORGANIZATION", "RETIRE_ORGANIZATION", "UPDATE_ORGANIZATION"}:
                if kind != "UPDATE_ORGANIZATION" or "security_domain_id" in payload:
                    affected.update(str(row["principal_id"]) for row in tx.query(
                        "SELECT DISTINCT m.PRINCIPAL_ID FROM CX_ORGANIZATION_MEMBERS m "
                        "JOIN CX_ORGANIZATION_CLOSURE c ON c.DESCENDANT_ID = m.ORGANIZATION_ID "
                        "WHERE c.ANCESTOR_ID = :organization_id AND m.STATUS = 'ACTIVE'",
                        {"organization_id": item.get("target_id")},
                    ))
                    affected_agents.update(str(row["agent_id"]) for row in tx.query(
                        "SELECT DISTINCT ar.AGENT_ID FROM CX_AGENT_RELATIONSHIPS ar "
                        "JOIN CX_ORGANIZATION_CLOSURE c ON c.DESCENDANT_ID = ar.RESPONSIBLE_ORGANIZATION_ID "
                        "WHERE c.ANCESTOR_ID = :organization_id AND ar.STATUS = 'ACTIVE'",
                        {"organization_id": item.get("target_id")},
                    ))
            before, after, principals, changed_structure, scope_organization_id = _apply_operation_tx(tx, item, actor_principal_id)
            affected.update(principals)
            if (item.get("payload") or {}).get("agent_id"):
                affected_agents.add(str((item.get("payload") or {})["agent_id"]))
            if before.get("agent_id"):
                affected_agents.add(str(before["agent_id"]))
            structural = structural or changed_structure
            history.append((item, before, after, scope_organization_id))
        closure_rows = _rebuild_closure_tx(tx) if structural else 0
        version_id = _id("OV")
        published_version = current_version["version_number"] + 1
        content_digest = _digest([
            {"operation_type": item[0].get("operation_type"), "target_type": item[0].get("target_type"),
             "target_id": item[0].get("target_id"), "after": item[2]} for item in history
        ])
        superseded = tx.execute(
            "UPDATE CX_ORGANIZATION_VERSIONS SET STATUS = 'SUPERSEDED' "
            "WHERE VERSION_ID = :parent_version_id AND STATUS = 'CURRENT'",
            {"parent_version_id": current_version["version_id"]},
        )
        if superseded != 1:
            raise OrganizationConflict("organization version changed")
        tx.execute(
            "INSERT INTO CX_ORGANIZATION_VERSIONS(VERSION_ID, VERSION_NUMBER, PARENT_VERSION_ID, CHANGE_SET_ID, "
            "STATUS, CONTENT_DIGEST, REASON, CREATED_BY) VALUES (:version_id, :version_number, "
            ":parent_version_id, :change_set_id, 'CURRENT', :content_digest, :reason, :created_by)",
            {"version_id": version_id, "version_number": published_version,
             "parent_version_id": current_version["version_id"], "change_set_id": change_id,
             "content_digest": content_digest, "reason": reason, "created_by": actor_principal_id},
        )
        for item, before, after, scope_organization_id in history:
            target_type = str(item.get("target_type") or "ORGANIZATION").upper()
            fact = after or before
            if target_type == "ORGANIZATION":
                operation = ("INSERT" if item["operation_type"] == "CREATE_ORGANIZATION" else
                             "RETIRE" if item["operation_type"] == "RETIRE_ORGANIZATION" else "UPDATE")
                tx.execute(
                    "INSERT INTO CX_ORGANIZATION_UNIT_HISTORY(HISTORY_ID, VERSION_ID, ORGANIZATION_ID, OPERATION, "
                    "VALID_FROM, VALID_UNTIL, FACT_JSON, FACT_DIGEST, ACTOR_PRINCIPAL_ID, REASON) "
                    "VALUES (:history_id, :version_id, :organization_id, :operation, :valid_from, :valid_until, "
                    ":fact_json, :fact_digest, :actor, :reason)",
                    {"history_id": _id("OUH"), "version_id": version_id,
                     "organization_id": scope_organization_id, "operation": operation,
                     "valid_from": fact.get("valid_from") or identity_api._now(), "valid_until": fact.get("valid_until"),
                     "fact_json": _json(fact), "fact_digest": _digest(fact), "actor": actor_principal_id, "reason": reason},
                )
            elif target_type == "MEMBERSHIP":
                operation = "END" if item["operation_type"] == "END_MEMBERSHIP" else "INSERT"
                tx.execute(
                    "INSERT INTO CX_ORGANIZATION_MEMBER_HISTORY(HISTORY_ID, VERSION_ID, MEMBERSHIP_ID, PRINCIPAL_ID, "
                    "ORGANIZATION_ID, OPERATION, VALID_FROM, VALID_UNTIL, FACT_JSON, FACT_DIGEST, "
                    "ACTOR_PRINCIPAL_ID, REASON) VALUES (:history_id, :version_id, :membership_id, :principal_id, "
                    ":organization_id, :operation, :valid_from, :valid_until, :fact_json, :fact_digest, :actor, :reason)",
                    {"history_id": _id("OMH"), "version_id": version_id,
                     "membership_id": fact.get("membership_id") or item["target_id"],
                     "principal_id": fact.get("principal_id"), "organization_id": scope_organization_id,
                     "operation": operation, "valid_from": fact.get("valid_from") or identity_api._now(),
                     "valid_until": fact.get("valid_until"), "fact_json": _json(fact), "fact_digest": _digest(fact),
                     "actor": actor_principal_id, "reason": reason},
                )
            elif target_type == "REPORTING":
                operation = "END" if item["operation_type"] == "END_REPORTING" else "INSERT"
                tx.execute(
                    "INSERT INTO CX_REPORTING_HISTORY(HISTORY_ID, VERSION_ID, RELATIONSHIP_ID, PRINCIPAL_ID, "
                    "MANAGER_PRINCIPAL_ID, OPERATION, VALID_FROM, VALID_UNTIL, FACT_JSON, FACT_DIGEST, "
                    "ACTOR_PRINCIPAL_ID, REASON) VALUES (:history_id, :version_id, :relationship_id, "
                    ":principal_id, :manager_principal_id, :operation, :valid_from, :valid_until, :fact_json, "
                    ":fact_digest, :actor, :reason)",
                    {"history_id": _id("ORH"), "version_id": version_id,
                     "relationship_id": fact.get("relationship_id") or item["target_id"],
                     "principal_id": fact.get("principal_id"), "manager_principal_id": fact.get("manager_principal_id"),
                     "operation": operation, "valid_from": fact.get("valid_from") or identity_api._now(),
                     "valid_until": fact.get("valid_until"), "fact_json": _json(fact), "fact_digest": _digest(fact),
                     "actor": actor_principal_id, "reason": reason},
                )
            elif target_type == "AGENT_RELATIONSHIP":
                operation = "END" if item["operation_type"] == "END_AGENT_RELATIONSHIP" else "INSERT"
                tx.execute(
                    "INSERT INTO CX_AGENT_RELATIONSHIP_HISTORY(HISTORY_ID, VERSION_ID, RELATIONSHIP_ID, AGENT_ID, "
                    "PRINCIPAL_ID, RELATIONSHIP_ROLE, RESPONSIBLE_ORGANIZATION_ID, OPERATION, FACT_JSON, "
                    "FACT_DIGEST, ACTOR_PRINCIPAL_ID, REASON) VALUES (:history_id, :version_id, :relationship_id, "
                    ":agent_id, :principal_id, :relationship_role, :responsible_organization_id, :operation, "
                    ":fact_json, :fact_digest, :actor, :reason)",
                    {"history_id": _id("OAH"), "version_id": version_id,
                     "relationship_id": fact.get("relationship_id") or item["target_id"],
                     "agent_id": fact.get("agent_id"), "principal_id": fact.get("principal_id"),
                     "relationship_role": fact.get("relationship_role"),
                     "responsible_organization_id": fact.get("responsible_organization_id"), "operation": operation,
                     "fact_json": _json(fact), "fact_digest": _digest(fact), "actor": actor_principal_id, "reason": reason},
                )
        for principal_id in sorted(affected):
            tx.execute(
                "UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE PRINCIPAL_ID = :principal_id",
                {"principal_id": principal_id},
            )
        for agent_id in sorted(affected_agents):
            tx.execute(
                "UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT'",
                {"agent_id": agent_id},
            )
            tx.execute(
                "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
                "WHERE AGENT_ID = :agent_id AND REVOKED_AT IS NULL",
                {"agent_id": agent_id},
            )
            tx.execute(
                "UPDATE CX_WEB_SESSIONS SET REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason "
                "WHERE PRINCIPAL_ID = :principal_id AND REVOKED_AT IS NULL",
                {"principal_id": principal_id, "reason": "organization authority changed"},
            )
            tx.execute(
                "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
                "WHERE REVOKED_AT IS NULL AND AGENT_ID IN (SELECT ar.AGENT_ID FROM CX_AGENT_RELATIONSHIPS ar "
                "WHERE ar.PRINCIPAL_ID = :principal_id AND ar.STATUS = 'ACTIVE')",
                {"principal_id": principal_id},
            )
        changed = tx.execute(
            "UPDATE CX_ORG_CHANGESETS SET STATUS = 'PUBLISHED', PUBLISHED_AT = CURRENT_TIMESTAMP, "
            "OUTCOME_JSON = :outcome_json, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE CHANGE_SET_ID = :change_id AND STATUS = 'PUBLISHING'",
            {"outcome_json": _json({"version_id": version_id, "version_number": published_version,
                                    "published_by": actor_principal_id}), "change_id": change_id},
        )
        if changed != 1:
            raise OrganizationConflict("organization change was published concurrently")
        if approval_id:
            approved = tx.execute(
                "UPDATE APPROVAL_REQUESTS SET APPROVAL_STATUS = 'APPROVED', APPROVED_BY = :approver, "
                "APPROVED_AT = CURRENT_TIMESTAMP WHERE APPROVAL_ID = :approval_id "
                "AND ENTITY_TYPE = 'ORGANIZATION_CHANGE' AND ENTITY_ID = :change_id "
                "AND APPROVAL_STATUS = 'PENDING'",
                {"approver": actor_principal_id, "approval_id": approval_id, "change_id": change_id},
            )
            if approved != 1:
                raise OrganizationConflict("organization approval was decided concurrently")
            identity_api._audit_tx(tx, actor_principal_id, "ORG_CHANGESET_APPROVE", "APPROVAL_REQUEST", approval_id, "ALLOW", reason)
            if emergency_admin and str(change.get("author_principal_id") or "") == actor_principal_id:
                identity_api._audit_tx(
                    tx, actor_principal_id, "ORG_CHANGESET_EMERGENCY_SELF_APPROVE",
                    "APPROVAL_REQUEST", approval_id, "ALLOW", reason,
                )
        identity_api._audit_tx(tx, actor_principal_id, "ORG_CHANGESET_PUBLISH", "ORG_CHANGESET", change_id, "ALLOW", reason)
        return {"change_id": change_id, "status": "PUBLISHED", "published_version_id": version_id,
                "published_version": published_version,
                "operation_count": len(operations), "invalidated_principal_count": len(affected),
                "invalidated_agent_count": len(affected_agents),
                "closure_row_count": closure_rows}

    return connection.execute_transaction_callback(work)


def publish_low_risk(actor_principal_id: str, change_id: str, reason: str) -> Dict[str, Any]:
    """Publish a validated low-risk change without placing it in the approval queue."""
    _access(actor_principal_id, PUBLISH_ACTION)
    return _publish_change(actor_principal_id, change_id, reason, expected_status="VALIDATED", low_risk_only=True)


def publish_com_pending(actor_principal_id: str, change_id: str, reason: str) -> Dict[str, Any]:
    """Recover a legacy Community pending request without exposing ENT approvals."""
    if _approvals_enabled():
        raise OrganizationError("Community direct publication is unavailable")
    _access(actor_principal_id, PUBLISH_ACTION)
    reason = _text(reason, "reason", 2000, required=True)
    change = _change_for_actor(change_id, actor_principal_id, lock=False)
    if str(change.get("status") or "").upper() != "PENDING_APPROVAL":
        raise OrganizationConflict("organization change is not awaiting Community recovery")
    if _risk_for(_operations(change_id)) != "LOW":
        raise OrganizationError("organization change requires Enterprise approval")
    request = _row(connection.execute_query_one(
        "SELECT APPROVAL_ID FROM APPROVAL_REQUESTS WHERE ENTITY_TYPE='ORGANIZATION_CHANGE' "
        "AND ENTITY_ID=:change_id AND APPROVAL_STATUS='PENDING' ORDER BY CREATED_AT DESC " + _limit("one_row"),
        {"change_id": change_id, "one_row": 1},
    ))
    if not request:
        raise OrganizationConflict("organization approval request is missing")
    return _publish_change(
        actor_principal_id, change_id, reason,
        expected_status="PENDING_APPROVAL", low_risk_only=True,
        approval_id=str(request["approval_id"]),
    )


def approve_change(actor_principal_id: str, approval_id: str, reason: str) -> Dict[str, Any]:
    """Approve and publish one organization request as a single transaction."""
    _access(actor_principal_id, APPROVE_ACTION)
    reason = _text(reason, "reason", 500, required=True)
    request = _row(connection.execute_query_one(
        "SELECT APPROVAL_ID, ENTITY_ID, REQUESTED_BY, APPROVAL_STATUS FROM APPROVAL_REQUESTS "
        "WHERE APPROVAL_ID = :approval_id AND ENTITY_TYPE = 'ORGANIZATION_CHANGE'",
        {"approval_id": _text(approval_id, "approval_id", 256, required=True)},
    ))
    if not request:
        raise OrganizationError("organization approval is unavailable")
    if str(request.get("approval_status") or "").upper() != "PENDING":
        raise OrganizationConflict("organization approval is already decided")
    if (str(request.get("requested_by") or "") == actor_principal_id
            and not identity_api._protected_bootstrap_admin(actor_principal_id)):
        raise PermissionError("organization requester cannot approve their own change")
    return _publish_change(
        actor_principal_id, str(request["entity_id"]), reason,
        expected_status="PENDING_APPROVAL", low_risk_only=False, approval_id=str(request["approval_id"]),
    )


def reject_change(actor_principal_id: str, approval_id: str, reason: str) -> Dict[str, Any]:
    """Reject a submitted organization change and its queue item atomically."""
    _access(actor_principal_id, APPROVE_ACTION)
    reason = _text(reason, "reason", 500, required=True)

    def work(tx: Any) -> Dict[str, Any]:
        request = _row(tx.query_one(
            "SELECT APPROVAL_ID, ENTITY_ID, REQUESTED_BY, APPROVAL_STATUS FROM APPROVAL_REQUESTS "
            "WHERE APPROVAL_ID = :approval_id AND ENTITY_TYPE = 'ORGANIZATION_CHANGE' FOR UPDATE",
            {"approval_id": _text(approval_id, "approval_id", 256, required=True)},
        ))
        if not request:
            raise OrganizationError("organization approval is unavailable")
        if str(request.get("approval_status") or "").upper() != "PENDING":
            raise OrganizationConflict("organization approval is already decided")
        emergency_admin = identity_api._protected_bootstrap_admin(actor_principal_id)
        if (str(request.get("requested_by") or "") == actor_principal_id
                and not emergency_admin):
            raise PermissionError("organization requester cannot reject their own change")
        change_id = str(request["entity_id"])
        change = _change_for_decision(change_id, actor_principal_id, executor=tx)
        if str(change.get("status") or "").upper() != "PENDING_APPROVAL":
            raise OrganizationConflict("organization change is not awaiting approval")
        decided = tx.execute(
            "UPDATE APPROVAL_REQUESTS SET APPROVAL_STATUS = 'REJECTED', APPROVED_BY = :approver, "
            "APPROVED_AT = CURRENT_TIMESTAMP, REJECT_REASON = :reason WHERE APPROVAL_ID = :approval_id "
            "AND APPROVAL_STATUS = 'PENDING'",
            {"approver": actor_principal_id, "reason": reason, "approval_id": approval_id},
        )
        changed = tx.execute(
            "UPDATE CX_ORG_CHANGESETS SET STATUS = 'REJECTED', OUTCOME_JSON = :outcome_json, "
            "ROW_VERSION = ROW_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE CHANGE_SET_ID = :change_id AND STATUS = 'PENDING_APPROVAL'",
            {"outcome_json": _json({"decision": "REJECTED", "decided_by": actor_principal_id, "reason": reason}),
             "change_id": change_id},
        )
        if decided != 1 or changed != 1:
            raise OrganizationConflict("organization approval was decided concurrently")
        identity_api._audit_tx(tx, actor_principal_id, "ORG_CHANGESET_REJECT", "APPROVAL_REQUEST", approval_id, "DENY", reason)
        if emergency_admin and str(request.get("requested_by") or "") == actor_principal_id:
            identity_api._audit_tx(
                tx, actor_principal_id, "ORG_CHANGESET_EMERGENCY_SELF_REJECT",
                "APPROVAL_REQUEST", approval_id, "DENY", reason,
            )
        return {"approval_id": approval_id, "change_id": change_id, "status": "REJECTED"}

    return connection.execute_transaction_callback(work)


def approval_summary(actor_principal_id: str, change_id: str) -> Dict[str, Any]:
    """Return the bounded, secret-free organization review payload."""
    _access(actor_principal_id, APPROVE_ACTION)
    change = _row(connection.execute_query_one(
        "SELECT CHANGE_SET_ID, STATUS, BASE_VERSION_ID, AUTHOR_PRINCIPAL_ID, REASON, RISK_LEVEL, "
        "VALIDATION_JSON, IMPACT_JSON, CREATED_AT, SUBMITTED_AT FROM CX_ORG_CHANGESETS "
        "WHERE CHANGE_SET_ID = :change_id",
        {"change_id": _text(change_id, "change_id", 256, required=True)},
    ))
    if not change:
        raise OrganizationError("organization change is unavailable")
    operations = _operations(change_id)[:100]
    return {
        "change_id": change_id,
        "status": change.get("status"),
        "author_principal_id": change.get("author_principal_id"),
        "reason": change.get("reason"),
        "risk_level": change.get("risk_level"),
        "validation": _load_json(change.get("validation_json"), {}),
        "impact": _load_json(change.get("impact_json"), {}),
        "operations": [{"operation_type": item.get("operation_type"), "target_type": item.get("target_type"),
                        "target_id": item.get("target_id"), "after": item.get("payload")} for item in operations],
        "operation_count": len(operations),
        "created_at": change.get("created_at"),
        "submitted_at": change.get("submitted_at"),
    }


def list_changes(actor_principal_id: str, limit: int = 100, *, status: str = "") -> List[Dict[str, Any]]:
    _access(actor_principal_id, CHANGE_ACTION)
    access = identity_api.effective_access(actor_principal_id, "organizations.changes.read.all")
    params: Dict[str, Any] = {"limit": _bounded(limit)}
    clauses = [] if access.get("decision") == "ALLOW" else ["AUTHOR_PRINCIPAL_ID = :actor"]
    if clauses:
        params["actor"] = actor_principal_id
    if status:
        normalized = str(status).upper()
        if normalized not in CHANGE_STATUSES:
            raise OrganizationError("change status is invalid")
        params["status"] = normalized
        clauses.append("STATUS = :status")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return _query(
        "SELECT CHANGE_SET_ID, STATUS, BASE_VERSION_ID, AUTHOR_PRINCIPAL_ID, REASON, RISK_LEVEL, "
        "SCHEDULED_FOR, ACTION_CARD_ID, CREATED_AT, UPDATED_AT, PUBLISHED_AT, OUTCOME_JSON FROM CX_ORG_CHANGESETS" +
        where + " ORDER BY CREATED_AT DESC " + _limit(), params,
    )


def get_change_set(actor_principal_id: str, change_id: str) -> Dict[str, Any]:
    change = _change_for_actor(change_id, actor_principal_id)
    operations = _operations(change_id)
    impact = _query_one(
        "SELECT IMPACT_JSON FROM CX_ORG_CHANGESETS WHERE CHANGE_SET_ID = :change_id",
        {"change_id": change_id},
    ) or {}
    change["operations"] = operations
    change["impact"] = _load_json(impact.get("impact_json"), {})
    change["diff"] = {
        "operations": [
            {
                "operation_type": item.get("operation_type"),
                "target_type": item.get("target_type"),
                "target_id": item.get("target_id"),
                "after": item.get("payload"),
            }
            for item in operations
        ]
    }
    return change


def list_history(actor_principal_id: str, limit: int = 100, *, organization_id: str = "") -> List[Dict[str, Any]]:
    clause, params = _scope_clause(actor_principal_id, "o", HISTORY_ACTION)
    params["limit"] = _bounded(limit)
    target = ""
    if organization_id:
        params["organization_id"] = _text(organization_id, "organization_id", 256, required=True)
        target = " AND history_rows.ORGANIZATION_ID = :organization_id"
    rows = _query(
        "SELECT history_rows.HISTORY_ID, history_rows.VERSION_ID, v.VERSION_NUMBER, v.CHANGE_SET_ID, "
        "history_rows.TARGET_TYPE, history_rows.TARGET_ID, history_rows.ORGANIZATION_ID, "
        "history_rows.OPERATION, history_rows.FACT_JSON, history_rows.ACTOR_PRINCIPAL_ID, "
        "history_rows.REASON, history_rows.RECORDED_AT FROM ("
        "SELECT uh.HISTORY_ID, uh.VERSION_ID, 'ORGANIZATION' AS TARGET_TYPE, uh.ORGANIZATION_ID AS TARGET_ID, "
        "uh.ORGANIZATION_ID, uh.OPERATION, uh.FACT_JSON, uh.ACTOR_PRINCIPAL_ID, uh.REASON, uh.RECORDED_AT "
        "FROM CX_ORGANIZATION_UNIT_HISTORY uh UNION ALL "
        "SELECT mh.HISTORY_ID, mh.VERSION_ID, 'MEMBERSHIP' AS TARGET_TYPE, mh.MEMBERSHIP_ID AS TARGET_ID, "
        "mh.ORGANIZATION_ID, mh.OPERATION, mh.FACT_JSON, mh.ACTOR_PRINCIPAL_ID, mh.REASON, mh.RECORDED_AT "
        "FROM CX_ORGANIZATION_MEMBER_HISTORY mh UNION ALL "
        "SELECT rh.HISTORY_ID, rh.VERSION_ID, 'REPORTING' AS TARGET_TYPE, rh.RELATIONSHIP_ID AS TARGET_ID, "
        "rm.ORGANIZATION_ID, rh.OPERATION, rh.FACT_JSON, rh.ACTOR_PRINCIPAL_ID, rh.REASON, rh.RECORDED_AT "
        "FROM CX_REPORTING_HISTORY rh JOIN CX_ORGANIZATION_MEMBERS rm ON rm.PRINCIPAL_ID = rh.PRINCIPAL_ID "
        "AND rm.MEMBERSHIP_KIND = 'PRIMARY' AND rm.STATUS = 'ACTIVE'"
        ") history_rows JOIN CX_ORGANIZATION_VERSIONS v ON v.VERSION_ID = history_rows.VERSION_ID "
        "JOIN CX_ORGANIZATIONS o ON o.ORGANIZATION_ID = history_rows.ORGANIZATION_ID WHERE " + clause + target +
        " ORDER BY v.VERSION_NUMBER DESC, history_rows.RECORDED_AT DESC " + _limit(), params,
    )
    for row in rows:
        row["fact"] = _load_json(row.pop("fact_json", "{}"), {})
    return rows


def _normalize_import_record(record: Mapping[str, Any], index: int) -> Dict[str, Any]:
    kind = str(record.get("record_type") or record.get("kind") or "").strip().upper()
    if kind not in {"ORGANIZATION", "PERSON", "MEMBERSHIP", "REPORTING"}:
        raise OrganizationError(f"import record {index} has an invalid type")
    external_id = _text(record.get("external_object_id") or record.get("external_id"), "external_object_id", 512, required=True)
    clean = {str(key).strip().lower(): value for key, value in record.items() if str(key).strip()}
    for protected in ("permissions", "roles", "security_domain_id", "agent_relationships", "password", "secret"):
        clean.pop(protected, None)
    clean["record_type"] = kind
    clean["external_object_id"] = external_id
    return clean


def _stage_records(actor_principal_id: str, connector_id: str, records: Sequence[Mapping[str, Any]], source_format: str, reason: str = "directory data staged") -> Dict[str, Any]:
    _access(actor_principal_id, SYNC_ACTION)
    connector_id = _text(connector_id, "connector_id", 256, required=True)
    if not records or len(records) > MAX_IMPORT_RECORDS:
        raise OrganizationError("import record count is invalid")
    normalized = [_normalize_import_record(record, index + 1) for index, record in enumerate(records)]
    batch_id = _id("DSB")
    payload_digest = _digest(normalized)

    def work(tx: Any) -> Dict[str, Any]:
        tx.execute(
            "INSERT INTO CX_DIRECTORY_SYNC_BATCHES(SYNC_BATCH_ID, CONNECTOR_ID, CONNECTOR_TYPE, SOURCE_DIGEST, "
            "STATUS, REQUESTED_BY, TOTAL_RECORDS) VALUES (:sync_batch_id, :connector_id, :connector_type, "
            ":source_digest, 'STAGING', :requested_by, :total_records)",
            {"sync_batch_id": batch_id, "connector_id": connector_id, "connector_type": source_format,
             "source_digest": payload_digest, "total_records": len(normalized), "requested_by": actor_principal_id},
        )
        for index, record in enumerate(normalized, 1):
            tx.execute(
                "INSERT INTO CX_DIRECTORY_SOURCE_RECORDS(SOURCE_RECORD_ID, SYNC_BATCH_ID, CONNECTOR_ID, "
                "EXTERNAL_OBJECT_ID, OBJECT_TYPE, SOURCE_DIGEST, NORMALIZED_JSON, STATUS) "
                "VALUES (:source_record_id, :sync_batch_id, :connector_id, :external_object_id, :object_type, "
                ":source_digest, :normalized_json, 'STAGED')",
                {"source_record_id": _id("DSR"), "sync_batch_id": batch_id, "connector_id": connector_id,
                 "object_type": record["record_type"], "external_object_id": record["external_object_id"],
                 "source_digest": _digest(record), "normalized_json": _json(record)},
            )
        identity_api._audit_tx(tx, actor_principal_id, "ORG_DIRECTORY_STAGE", "DIRECTORY_SYNC_BATCH", batch_id, "ALLOW", reason)
        return {"batch_id": batch_id, "status": "STAGING", "record_count": len(normalized),
                "source_digest": payload_digest, "connector_type": source_format}

    return connection.execute_transaction_callback(work)


def stage_json(actor_principal_id: str, connector_id: str, payload: Any) -> Dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        if len(payload) > MAX_IMPORT_BYTES:
            raise OrganizationError("import payload is too large")
        payload = bytes(payload).decode("utf-8")
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_IMPORT_BYTES:
            raise OrganizationError("import payload is too large")
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise OrganizationError("JSON import is invalid") from exc
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise OrganizationError("JSON import must contain a record list")
    return _stage_records(actor_principal_id, connector_id, records, "JSON")


def stage_csv(actor_principal_id: str, connector_id: str, payload: Any) -> Dict[str, Any]:
    if isinstance(payload, bytes):
        if len(payload) > MAX_IMPORT_BYTES:
            raise OrganizationError("import payload is too large")
        try:
            payload = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise OrganizationError("CSV import must be UTF-8") from exc
    text = str(payload or "")
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES or "\x00" in text:
        raise OrganizationError("import payload is invalid")
    try:
        records = list(csv.DictReader(io.StringIO(text)))
    except (csv.Error, UnicodeError) as exc:
        raise OrganizationError("CSV import is invalid") from exc
    if not records or not records[0]:
        raise OrganizationError("CSV import has no records")
    return _stage_records(actor_principal_id, connector_id, records, "CSV")


def list_sync_conflicts(actor_principal_id: str, limit: int = 100, *, batch_id: str = "") -> List[Dict[str, Any]]:
    access = _access(actor_principal_id, SYNC_ACTION)
    global_scope = "ALL" in {str(item).upper() for item in access.get("scopes", [])}
    params: Dict[str, Any] = {"limit": _bounded(limit)}
    where = ""
    if batch_id:
        params["batch_id"] = _text(batch_id, "batch_id", 256, required=True)
        where = " WHERE c.SYNC_BATCH_ID = :batch_id"
    rows = _query(
        "SELECT c.CONFLICT_ID, c.SYNC_BATCH_ID, c.SOURCE_RECORD_ID, c.OBJECT_TYPE, c.OBJECT_ID, "
        "c.FIELD_NAME, c.AUTHORITY_SOURCE, c.SOURCE_DIGEST, c.PLATFORM_DIGEST, c.RISK_LEVEL, "
        "c.STATUS, c.RESOLUTION, c.RESOLUTION_REASON, c.RESOLVED_BY, c.OVERRIDE_UNTIL, "
        "c.RESOLVED_AT, c.CREATED_AT "
        "FROM CX_DIRECTORY_CONFLICTS c" + where + " ORDER BY c.CREATED_AT DESC " + _limit(), params,
    )
    # A target ID is returned only when its current organization remains visible.
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        target_type = str(row.get("object_type") or "").upper()
        target_id = str(row.get("object_id") or "")
        if target_type == "ORGANIZATION":
            if not _visible_organization(actor_principal_id, target_id, SYNC_ACTION):
                continue
        elif target_type in {"PERSON", "HUMAN"}:
            if not identity_api._principal_visible_to(actor_principal_id, target_id):
                continue
        elif target_type == "AGENT":
            if not identity_api._agent_visible_to(actor_principal_id, target_id):
                continue
        elif not global_scope:
            # Unknown target classes cannot be disclosed by a generic conflict endpoint.
            continue
        filtered.append(row)
    return filtered


def stage_import(actor: str, connector_type: str, records: Sequence[Mapping[str, Any]], reason: str) -> Dict[str, Any]:
    """Stage normalized connector records without applying directory authority."""
    connector = str(connector_type or "").upper()
    if connector not in {"CSV", "JSON", "LDAP"}:
        raise OrganizationError("connector type is invalid")
    reason = _text(reason, "reason", 2000, required=True)
    if not isinstance(records, (list, tuple)) or not all(isinstance(item, Mapping) for item in records):
        raise OrganizationError("import records are invalid")
    return _stage_records(actor, connector, records, connector, reason)


def get_node(actor: str, organization_id: str) -> Dict[str, Any]:
    return get_detail(actor, organization_id)


def impact_change_set(actor: str, change_set_id: str) -> Dict[str, Any]:
    return calculate_impact(actor, change_set_id)


def publish_change_set(actor: str, change_set_id: str) -> Dict[str, Any]:
    change = _change_for_actor(change_set_id, actor)
    return publish_low_risk(actor, change_set_id, str(change.get("reason") or "governed organization publication"))


# Explicit aliases keep service names readable at HTTP integration points.
search_organizations = search
get_organization_detail = get_node
create_draft = create_change_set
validate_draft = validate_change_set
impact = calculate_impact
publish = publish_low_risk
