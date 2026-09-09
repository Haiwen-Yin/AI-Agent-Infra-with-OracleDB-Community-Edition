"""Offline profile authorization, immutability and inherited-lock regressions."""
import hashlib
from unittest.mock import Mock

import pytest
from lib import compliance_api as api


def version(key, content, parent="", status="PUBLISHED"):
    raw = api._json(content)
    return dict(profile_version_id=key, profile_id="profile", parent_version_id=parent,
                status=status, content_json=raw, content_digest=hashlib.sha256(raw.encode()).hexdigest())


def tx_for(*versions):
    rows = {item["profile_version_id"]: item for item in versions}
    return Mock(query_one=Mock(side_effect=lambda sql, params: dict(rows[params["id"]]) if params["id"] in rows else None), execute=Mock(return_value=1))


@pytest.mark.parametrize("field", ["database", "database_access", "controls.database"])
def test_nested_locked_control_cannot_be_overridden(field):
    parent = version("parent", {"locked_fields": [field], "controls": {"database": "gateway_only"}})
    child = version("child", {"controls": {"database_access": "unrestricted"}}, "parent", "DRAFT")
    with pytest.raises(api.ComplianceError, match="locked"):
        api._resolve_profile_tx(tx_for(parent), child)


def test_grandparent_constraints_and_sources_survive_omission():
    root = version("root", {"locked_fields": ["network"], "controls": {"network": "isolated"}})
    parent = version("parent", {"controls": {"audit": "immutable"}}, "root")
    child = version("child", {"locked_fields": [], "controls": {"database": "gateway_only"}}, "parent", "DRAFT")
    result = api._resolve_profile_tx(tx_for(root, parent), child)
    assert result["effective_content"]["controls"] == {"network": "isolated", "audit": "immutable", "database": "gateway_only"}
    assert result["effective_content"]["locked_fields"] == ["network"]
    assert result["field_sources"]["controls.network"] == "root"


@pytest.mark.parametrize("mode", ["cycle", "draft_parent", "tampered", "missing"])
def test_invalid_inheritance_fails_closed(mode):
    parent = version("parent", {}, "child" if mode == "cycle" else "", "DRAFT" if mode == "draft_parent" else "PUBLISHED")
    if mode == "tampered": parent["content_json"] = '{"changed":true}'
    child = version("child", {}, "parent", "DRAFT")
    with pytest.raises(api.ComplianceError):
        api._resolve_profile_tx(tx_for(*([] if mode == "missing" else [parent])), child)


@pytest.fixture
def authorized(monkeypatch):
    monkeypatch.setattr(api, "_enterprise_enabled", lambda: True)
    monkeypatch.setattr(api, "_require", Mock())
    monkeypatch.setattr(api, "_audit_tx", Mock())


def test_publish_reads_parent_and_rejects_override(authorized, monkeypatch):
    parent = version("parent", {"locked_fields": ["database"], "controls": {"database": "gateway_only"}})
    child = version("child", {"controls": {"database": "open"}}, "parent", "DRAFT")
    tx = tx_for(parent, child)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(api.ComplianceError, match="locked"):
        api.publish_profile("admin", "child", "reviewed")
    assert "PARENT_VERSION_ID" in tx.query_one.call_args_list[0].args[0]
    tx.execute.assert_not_called()


@pytest.mark.parametrize("status,digest", [("PUBLISHED", "match"), ("DRAFT", "stale")])
def test_edit_rejects_immutable_or_stale_before_write(authorized, monkeypatch, status, digest):
    item = version("v1", {}, status=status)
    tx = tx_for(item)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(api.ProfileConflict):
        api.update_profile_draft("admin", "v1", {}, item["content_digest"] if digest == "match" else "0" * 64, "reviewed")
    tx.execute.assert_not_called()


@pytest.mark.parametrize("operation", ["read", "edit"])
@pytest.mark.parametrize("denial", ["community", "permission"])
def test_new_endpoints_check_authority_before_database(monkeypatch, operation, denial):
    monkeypatch.setattr(api, "_enterprise_enabled", lambda: denial != "community")
    monkeypatch.setattr(api, "_require", Mock(side_effect=PermissionError("denied")))
    database = Mock()
    monkeypatch.setattr(api.connection, "execute_transaction_callback", database)
    with pytest.raises((api.ComplianceError, PermissionError)):
        if operation == "read": api.get_profile_version("user", "v1")
        else: api.update_profile_draft("user", "v1", {}, "0" * 64, "reviewed")
    database.assert_not_called()


def test_edit_uses_compare_and_swap_and_audit(authorized, monkeypatch):
    item = version("v1", {}, status="DRAFT")
    tx = tx_for(item)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    result = api.update_profile_draft("admin", "v1", {"controls": {"network": "isolated"}}, item["content_digest"], "reviewed")
    assert result["content_digest"] != item["content_digest"]
    assert tx.execute.call_args.args[1]["expected"] == item["content_digest"]
    api._audit_tx.assert_called_once()


def test_invalid_old_draft_remains_inspectable_without_claiming_effective_policy(authorized, monkeypatch):
    child = version("child", {"controls": {"network": "open"}}, "missing", "DRAFT")
    tx = tx_for(child)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    result = api.get_profile_version("admin", "child")
    assert result["validation"]["status"] == "INVALID"
    assert result["effective_content"] is None
    assert result["content"]["controls"]["network"] == "open"


def test_valid_root_profile_still_publishes(authorized, monkeypatch):
    from lib import governed_approval
    approval = Mock()
    monkeypatch.setattr(governed_approval, "require_tx", approval)
    item = version("v1", {"controls": {"network": "isolated"}}, status="DRAFT")
    tx = tx_for(item)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    assert api.publish_profile("admin", "v1", "reviewed")["status"] == "PUBLISHED"
    assert tx.execute.call_count == 2
    approval.assert_called_once()


def test_all_controls_lock_rejects_new_control():
    parent = version("parent", {"locked_fields": ["controls"], "controls": {"network": "isolated"}})
    child = version("child", {"controls": {"database": "open"}}, "parent", "DRAFT")
    with pytest.raises(api.ComplianceError, match="locked"):
        api._resolve_profile_tx(tx_for(parent), child)


def test_validation_resolves_candidate_without_writing(authorized, monkeypatch):
    item = version("v1", {}, status="DRAFT")
    tx = tx_for(item)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    result = api.validate_profile_draft("admin", "v1", {"controls": {"network": "isolated"}}, item["content_digest"])
    assert result["effective_content"]["controls"]["network"] == "isolated"
    assert result["expected_digest"] == item["content_digest"]
    tx.execute.assert_not_called()


def test_validation_rejects_stale_source(authorized, monkeypatch):
    tx = tx_for(version("v1", {}))
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(api.ProfileConflict):
        api.validate_profile_draft("admin", "v1", {}, "0" * 64)
    tx.execute.assert_not_called()


def test_create_rejects_locked_parent_before_insert(authorized, monkeypatch):
    parent = version("parent", {"locked_fields": ["network"], "controls": {"network": "isolated"}})
    tx = tx_for(parent)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(api.ComplianceError, match="locked"):
        api.create_profile_draft("admin", "child", "Child", {"controls": {"network": "open"}}, "reviewed", "parent")
    tx.execute.assert_not_called()


def test_clone_rejects_stale_source_before_insert(authorized, monkeypatch):
    tx = tx_for(version("source", {}))
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(api.ProfileConflict):
        api.create_profile_draft("admin", "copy", "Copy", {}, "reviewed",
                                 source_version_id="source", expected_source_digest="0" * 64)
    tx.execute.assert_not_called()


def test_clone_preserves_parent_constraints(authorized, monkeypatch):
    parent = version("parent", {"locked_fields": ["network"], "controls": {"network": "isolated"}})
    source = version("source", {}, "parent")
    tx = tx_for(parent, source)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(api.ComplianceError, match="locked"):
        api.create_profile_draft("admin", "copy", "Copy", {"controls": {"network": "open"}}, "reviewed",
                                 source_version_id="source", expected_source_digest=source["content_digest"])
    tx.execute.assert_not_called()


@pytest.mark.parametrize("content", [
    {"unknown": True}, {"controls": {"network": None}}, {"controls": {"network": "unrestricted"}},
    {"controls": {"netwrok": "isolated"}}, {"controls": {"allowed_tools": "tool"}},
    {"controls": {"allowed_tools": ["tool", "tool"]}}, {"locked_fields": ["unknown"]},
    {"controls": {"network": "isolated", "network_egress": "allowlist"}},
])
def test_invalid_schema_cannot_be_saved(authorized, monkeypatch, content):
    item = version("v1", {}, status="DRAFT")
    tx = tx_for(item)
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(api.ComplianceError, match="schema"):
        api.update_profile_draft("admin", "v1", content, item["content_digest"], "reviewed")
    tx.execute.assert_not_called()


def test_seed_profiles_satisfy_mutation_schema():
    for _, _, content in api.SEED_PROFILES:
        api._validate_profile_schema(content)
