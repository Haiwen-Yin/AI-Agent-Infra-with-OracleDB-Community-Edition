"""Focused pure contracts for the v4.3.1 organization service."""

from __future__ import annotations

import re
import inspect
from pathlib import Path
from typing import Any

import pytest

from lib import organization_api


class FakeConnection:
    DATABASE_DIALECT = "postgresql"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.version = 7
        self.version_id = "version-7"
        self.change = {
            "change_set_id": "change-1", "status": "DRAFT", "base_version_id": "version-7",
            "author_principal_id": "admin", "reason": "test", "risk_level": "LOW", "row_version": 1,
        }
        self.operations: list[dict[str, Any]] = []
        self.organizations = {
            "root": {"organization_id": "root", "parent_id": None, "organization_code": "ROOT", "organization_name": "Root", "organization_type": "GROUP", "sort_order": 0, "status": "ACTIVE", "row_version": 3},
            "child": {"organization_id": "child", "parent_id": "root", "organization_code": "CHILD", "organization_name": "Child", "organization_type": "DEPARTMENT", "sort_order": 1, "status": "ACTIVE", "row_version": 2},
        }

    def _record(self, sql: str, params: dict[str, Any] | None) -> dict[str, Any]:
        values = dict(params or {})
        self.calls.append((sql, values))
        return values

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        params = self._record(sql, params)
        upper = sql.upper()
        if "FROM CX_ORGANIZATION_VERSIONS" in upper:
            return {"version_id": self.version_id, "version_number": self.version}
        if "FROM CX_ORG_CHANGESETS" in upper:
            if "IDEMPOTENCY_KEY" in upper:
                return None
            return dict(self.change) if params.get("change_id") == "change-1" else None
        if "FROM CX_ORGANIZATIONS" in upper and "COUNT(" not in upper:
            oid = params.get("organization_id")
            if oid:
                return dict(self.organizations.get(oid) or {}) or None
            return None
        if "COUNT(*) AS CNT FROM CX_ORGANIZATION_CLOSURE" in upper:
            return {"cnt": 2}
        return None

    def execute_query(self, sql: str, params: dict[str, Any] | None = None):
        params = self._record(sql, params)
        upper = sql.upper()
        if "FROM CX_ORG_CHANGE_OPERATIONS" in upper:
            return [dict(item) for item in self.operations]
        if "SELECT ORGANIZATION_ID, PARENT_ID, ROW_VERSION FROM CX_ORGANIZATIONS" in upper:
            return [dict(item) for item in self.organizations.values()]
        if "FROM CX_ORGANIZATIONS O" in upper:
            if "O.PARENT_ID = :PARENT_ID" in upper:
                return [dict(item) for item in self.organizations.values() if item["parent_id"] == params.get("parent_id")]
            return [dict(self.organizations["root"])]
        return []

    query_one = execute_query_one
    query = execute_query

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        params = self._record(sql, params)
        upper = sql.upper()
        if "INSERT INTO CX_ORG_CHANGE_OPERATIONS" in upper:
            self.operations.append({
                "operation_id": params["operation_id"], "change_set_id": params["change_set_id"],
                "sequence_number": params["sequence_number"], "operation_type": params["operation_type"],
                "target_type": params["target_type"], "target_id": params["target_id"],
                "expected_row_version": params["expected_row_version"],
                "command_json": params["command_json"], "status": "ACTIVE",
            })
        elif "STATUS = 'PUBLISHED'" in upper:
            self.change["status"] = "PUBLISHED"
        elif "UPDATE CX_ORG_CHANGESETS SET STATUS =" in upper:
            self.change["status"] = params["status"]
            self.change["risk_level"] = params["risk_level"]
        elif "UPDATE CX_ORGANIZATIONS SET ORGANIZATION_NAME" in upper:
            row = self.organizations[params["organization_id"]]
            if row["row_version"] != params["expected_version"]:
                return 0
            row["organization_name"] = params["organization_name"]
            row["row_version"] += 1
        elif "UPDATE CX_ORGANIZATION_VERSIONS SET STATUS = 'SUPERSEDED'" in upper:
            return 1 if params["parent_version_id"] == self.version_id else 0
        elif "INSERT INTO CX_ORGANIZATION_VERSIONS" in upper:
            self.version = params["version_number"]
            self.version_id = params["version_id"]
        return 1

    def execute_transaction_callback(self, callback):
        return callback(self)


@pytest.fixture
def service(monkeypatch):
    db = FakeConnection()
    monkeypatch.setattr(organization_api, "connection", db)
    monkeypatch.setattr(
        organization_api.identity_api, "effective_access",
        lambda actor, action, **kwargs: {"decision": "ALLOW", "scopes": ["ALL"], "roles": ["SYSTEM_ADMIN"]},
    )
    monkeypatch.setattr(organization_api.identity_api, "_audit", lambda *args: None)
    monkeypatch.setattr(organization_api.identity_api, "_audit_tx", lambda *args: None)
    monkeypatch.setattr(organization_api.identity_api, "_principal_visible_to", lambda *args: True)
    monkeypatch.setattr(organization_api.identity_api, "_agent_visible_to", lambda *args: True)
    monkeypatch.setattr(organization_api.identity_api, "_id", lambda prefix: prefix + "_test")
    return db


def test_read_contract_is_scoped_bounded_and_uses_named_binds(service):
    db = service
    rows = organization_api.list_children("admin", "root", limit=9999)
    assert [row["organization_id"] for row in rows] == ["child"]
    sql, params = db.calls[-1]
    assert params["limit"] == organization_api.MAX_PAGE
    assert params["parent_id"] == "root"
    assert "LIMIT :limit" in sql
    assert not re.search(r"%(?:\([^)]+\))s", sql)


def test_scope_clause_uses_closure_and_primary_membership(monkeypatch, service):
    monkeypatch.setattr(
        organization_api.identity_api, "effective_access",
        lambda actor, action, **kwargs: {"decision": "ALLOW", "scopes": ["ORG_SUBTREE"]},
    )
    clause, params = organization_api._scope_clause("manager")
    assert "CX_ORGANIZATION_CLOSURE" in clause
    assert "MEMBERSHIP_KIND = 'PRIMARY'" in clause
    assert params == {"actor_principal_id": "manager"}


def test_security_domain_scope_intersects_organization_scope(monkeypatch, service):
    monkeypatch.setattr(
        organization_api.identity_api, "effective_access",
        lambda actor, action, **kwargs: {
            "decision": "ALLOW", "scopes": ["ORG_SUBTREE", "SECURITY_DOMAIN"]
        },
    )
    clause, _ = organization_api._scope_clause("manager")
    assert "CX_ORGANIZATION_CLOSURE" in clause
    assert "CX_DOMAIN_MEMBERS" in clause
    assert ") AND (" in clause


def test_search_never_interpolates_caller_text(service):
    db = service
    organization_api.search("admin", "x%' OR 1=1 --")
    sql, params = db.calls[-1]
    assert "OR 1=1" not in sql
    assert "OR 1=1" in params["pattern"]
    assert ":pattern" in sql


def test_graph_is_deterministic_and_does_not_persist_coordinates(service):
    graph = organization_api.assemble_graph("admin", "root", limit=10)
    assert graph["layout"] == "HIERARCHICAL"
    assert [node["id"] for node in graph["nodes"]] == ["org:root", "org:child"]
    assert all("x" not in node and "y" not in node for node in graph["nodes"])
    assert graph["edges"] == [{"id": "org-edge:root:child", "from": "org:root", "to": "org:child", "kind": "CONTAINS"}]


def test_anomaly_mode_does_not_repeat_normal_hierarchy(monkeypatch, service):
    monkeypatch.setattr(organization_api, "list_anomalies", lambda *args, **kwargs: [])
    graph = organization_api.organization_graph("admin", "root", "anomalies", 2, 10)
    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["anomalies"] == []


def test_anomaly_mode_builds_focused_exception_graph(monkeypatch, service):
    monkeypatch.setattr(
        organization_api,
        "list_anomalies",
        lambda *args, **kwargs: [{
            "subject_id": "HP_1234567890abcdef", "username": "Alice",
            "anomaly_type": "HUMAN_WITHOUT_PRIMARY_ORG", "status": "ACTIVE",
        }],
    )
    graph = organization_api.organization_graph("admin", "root", "anomalies", 2, 10)
    assert {node["id"] for node in graph["nodes"]} == {"org:root", "anomaly:HP_1234567890abcdef"}
    anomaly = next(node for node in graph["nodes"] if node["id"].startswith("anomaly:"))
    assert anomaly["anomaly"] is True
    assert graph["edges"][0]["kind"] == "HUMAN_WITHOUT_PRIMARY_ORG"


def test_append_operation_is_semantic_and_classifies_move_high_risk(service):
    db = service
    result = organization_api.append_operation(
        "admin", "change-1", "MOVE_ORGANIZATION", "ORGANIZATION", "child", {"parent_id": "root"}, 2,
    )
    assert result["risk_level"] == "HIGH"
    assert db.operations[0]["operation_type"] == "MOVE_ORGANIZATION"
    assert "x" not in db.operations[0]["command_json"]


def test_operation_rejects_canvas_coordinates_and_unknown_fields(service):
    with pytest.raises(organization_api.OrganizationError, match="unsupported fields"):
        organization_api.append_operation(
            "admin", "change-1", "MOVE_ORGANIZATION", "ORGANIZATION", "child", {"parent_id": "root", "x": 42},
        )


def test_cycle_validation_rejects_descendant_move(service):
    db = service
    db.operations.append({
        "operation_id": "op-1", "change_set_id": "change-1", "sequence_number": 1,
        "operation_type": "MOVE_ORGANIZATION", "target_type": "ORGANIZATION", "target_id": "root",
        "expected_row_version": 3, "command_json": '{"parent_id":"child"}', "status": "ACTIVE",
    })
    result = organization_api.validate_change_set("admin", "change-1")
    assert result["valid"] is False
    assert "ORGANIZATION_CYCLE" in {item["code"] for item in result["errors"]}


def test_stale_row_and_base_versions_are_reported(service):
    db = service
    db.change["base_version_id"] = "version-6"
    db.operations.append({
        "operation_id": "op-1", "change_set_id": "change-1", "sequence_number": 1,
        "operation_type": "RENAME_ORGANIZATION", "target_type": "ORGANIZATION", "target_id": "child",
        "expected_row_version": 1, "command_json": '{"organization_name":"Renamed"}', "status": "ACTIVE",
    })
    result = organization_api.validate_change_set("admin", "change-1")
    codes = {item["code"] for item in result["errors"]}
    assert {"STALE_BASE_VERSION", "STALE_ROW_VERSION"} <= codes


def test_low_risk_publish_uses_one_transaction_and_records_evidence(service):
    db = service
    db.change["status"] = "VALIDATED"
    db.operations.append({
        "operation_id": "op-1", "change_set_id": "change-1", "sequence_number": 1,
        "operation_type": "RENAME_ORGANIZATION", "target_type": "ORGANIZATION", "target_id": "child",
        "expected_row_version": 2, "command_json": '{"organization_name":"Renamed"}', "status": "ACTIVE",
    })
    result = organization_api.publish_low_risk("admin", "change-1", "approved low risk correction")
    assert result["status"] == "PUBLISHED"
    assert result["published_version"] == 8
    assert db.organizations["child"]["organization_name"] == "Renamed"
    statements = [sql.upper() for sql, _ in db.calls]
    assert any("FOR UPDATE" in sql and "CX_ORG_CHANGESETS" in sql for sql in statements)
    assert any("INSERT INTO CX_ORGANIZATION_UNIT_HISTORY" in sql for sql in statements)
    assert any("INSERT INTO CX_ORGANIZATION_VERSIONS" in sql for sql in statements)


def test_high_risk_publish_fails_closed(service):
    db = service
    db.change["status"] = "VALIDATED"
    db.operations.append({
        "operation_id": "op-1", "change_set_id": "change-1", "sequence_number": 1,
        "operation_type": "MOVE_ORGANIZATION", "target_type": "ORGANIZATION", "target_id": "child",
        "expected_row_version": 2, "command_json": '{"parent_id":"root"}', "status": "ACTIVE",
    })
    with pytest.raises(organization_api.OrganizationError, match="requires approval"):
        organization_api.publish_low_risk("admin", "change-1", "move")


def test_json_staging_removes_protected_authority_fields(service):
    db = service
    result = organization_api.stage_json("admin", "ldap-1", [{
        "record_type": "person", "external_object_id": "user-1", "name": "Alice",
        "roles": ["SYSTEM_ADMIN"], "security_domain_id": "secret-domain",
    }])
    assert result["record_count"] == 1
    inserts = [(sql, params) for sql, params in db.calls if "CX_DIRECTORY_SOURCE_RECORDS" in sql]
    assert len(inserts) == 1
    payload = inserts[0][1]["normalized_json"]
    assert "SYSTEM_ADMIN" not in payload and "secret-domain" not in payload


def test_csv_staging_requires_utf8_and_external_identity(service):
    with pytest.raises(organization_api.OrganizationError, match="UTF-8"):
        organization_api.stage_csv("admin", "ldap-1", b"\xff\xfe")
    with pytest.raises(organization_api.OrganizationError, match="external_object_id"):
        organization_api.stage_csv("admin", "ldap-1", "record_type,name\nperson,Alice\n")


def test_no_positional_or_interpolated_value_binds_in_module():
    source = open(organization_api.__file__, encoding="utf-8").read()
    assert "%s" not in source
    assert "?" not in source
    assert "execute_query(f\"" not in source
    assert "execute(f\"" not in source


def test_service_uses_authoritative_step_19_schema_names():
    source = open(organization_api.__file__, encoding="utf-8").read().upper()
    for required in (
        "CX_ORGANIZATION_VERSIONS", "CX_ORGANIZATION_UNIT_HISTORY",
        "CX_ORGANIZATION_MEMBER_HISTORY", "CX_REPORTING_HISTORY",
        "CHANGE_SET_ID", "BASE_VERSION_ID", "AUTHOR_PRINCIPAL_ID",
        "SYNC_BATCH_ID", "CONNECTOR_TYPE", "SOURCE_DIGEST", "REQUESTED_BY",
        "OBJECT_TYPE", "NORMALIZED_JSON", "PRINCIPAL_ID",
    ):
        assert required in source
    for obsolete in ("CX_ORG_VERSIONS", "CX_ORG_HISTORY", "REPORT_PRINCIPAL_ID", "CHANGESET_ID"):
        assert obsolete not in source
    for obsolete_column in ("SEQUENCE_NO", "EXPECTED_VERSION", "PAYLOAD_JSON", "SOURCE_FORMAT"):
        assert not re.search(rf"\b(?:SELECT|INSERT|UPDATE)[^\n]*\b{obsolete_column}\b", source)


def test_web_integration_function_signatures_are_stable():
    expected = {
        "list_roots": ["actor_principal_id", "limit"],
        "organization_graph": ["actor", "root_id", "mode", "depth", "limit"],
        "search": ["actor_principal_id", "query", "limit"],
        "get_node": ["actor", "organization_id"],
        "list_changes": ["actor_principal_id", "limit", "status"],
        "create_change_set": ["actor_principal_id", "reason", "idempotency_key", "scheduled_at"],
        "append_operation": ["actor_principal_id", "change_id", "operation_type", "target_type", "target_id", "command", "expected_row_version"],
        "validate_change_set": ["actor_principal_id", "change_id"],
        "impact_change_set": ["actor", "change_set_id"],
        "publish_change_set": ["actor", "change_set_id"],
        "list_history": ["actor_principal_id", "limit", "organization_id"],
        "list_sync_conflicts": ["actor_principal_id", "limit", "batch_id"],
        "stage_import": ["actor", "connector_type", "records", "reason"],
    }
    for name, parameters in expected.items():
        assert list(inspect.signature(getattr(organization_api, name)).parameters) == parameters


def test_fastapi_exposes_organization_routes_with_governed_dependencies():
    source = (Path(organization_api.__file__).resolve().parents[1] / "web_app.py").read_text(encoding="utf-8")
    for declaration in (
        '@app.get("/api/organization/roots")',
        '@app.get("/api/organization/options")',
        '@app.get("/api/organization/graph")',
        '@app.get("/api/organization/search")',
        '@app.get("/api/organization/nodes/{organization_id}")',
        '@app.post("/api/organization/changes")',
        '@app.post("/api/organization/changes/{change_id}/operations")',
        '@app.post("/api/organization/changes/{change_id}/{action}")',
        '@app.get("/api/organization/history")',
        '@app.get("/api/organization/sync/conflicts")',
    ):
        assert declaration in source
    assert "organization_api" in source
    assert "require_action(\"organizations." in source


def test_organization_membership_requires_existing_login_and_excludes_bootstrap_admin():
    source = Path(organization_api.__file__).read_text(encoding="utf-8")
    append = source.split("def append_operation(", 1)[1].split("\ndef _proposed_parents", 1)[0]
    assert "has_active_login_identity" in append
    assert "_protected_bootstrap_admin" in append
    assert "organization person requires an active login account" in append


def test_organization_canvas_spacing_exceeds_constrained_node_size():
    scripts_root = Path(organization_api.__file__).resolve().parents[1]
    source_path = scripts_root / "web" / "src" / "App.tsx"
    if not source_path.is_file():
        compiled = scripts_root.parent / "web" / "dist" / "assets"
        source = "\n".join(path.read_text(encoding="utf-8") for path in compiled.glob("*.js"))
        assert "widthConstraint:{minimum:135,maximum:180}" in source
        assert re.search(r'nodeSpacing:[^,}]+\?230:125', source)
        assert re.search(r'levelSeparation:[^,}]+\?155:240', source)
        assert "treeSpacing:260" in source
        return
    source = source_path.read_text(encoding="utf-8")
    assert 'widthConstraint: { minimum: 135, maximum: 180 }' in source
    assert 'nodeSpacing: orientation === "UD" ? 230 : 125' in source
    assert 'levelSeparation: orientation === "UD" ? 155 : 240' in source
    assert "treeSpacing: 260" in source
    assert "function organizationCanvasLabel" in source
    assert "function organizationDetailValue" in source
    assert "requestId !== graphRequest.current" in source
    assert 'depth: "10"' in source
    assert "[...roots, ...scopeNodes]" in source


def test_change_set_creation_has_actor_scoped_idempotency(service):
    db = service
    result = organization_api.create_change_set("admin", "reorganize finance", "request-1")
    assert result["idempotent"] is False
    insert = next((sql, params) for sql, params in db.calls if "INSERT INTO CX_ORG_CHANGESETS" in sql)
    assert insert[1]["idempotency_key"] == "request-1"
    assert "AUTHOR_PRINCIPAL_ID = :author_principal_id" in next(sql for sql, _ in db.calls if "IDEMPOTENCY_KEY" in sql and "SELECT" in sql)


@pytest.mark.parametrize("dialect, limiter", [
    ("postgresql", "LIMIT :limit"),
    ("oracle", "FETCH FIRST :limit ROWS ONLY"),
    ("yashandb", "FETCH FIRST :limit ROWS ONLY"),
])
def test_portable_limiters_keep_named_binds(service, dialect, limiter):
    service.DATABASE_DIALECT = dialect
    assert organization_api._limit() == limiter
