from lib import security_domain_api
import pytest


def test_legacy_read_contract_is_explicitly_deprecated_and_scoped(monkeypatch):
    captured = {}
    monkeypatch.setattr(security_domain_api, "_require", lambda _actor: None)
    monkeypatch.setattr(
        security_domain_api.connection,
        "execute_query",
        lambda sql, params: captured.update(sql=sql, params=params) or [{"group_id": "G1", "group_name": "History"}],
    )
    rows = security_domain_api.list_collaboration_groups("P1")
    assert rows[0]["compatibility"]["deprecated"] is True
    assert rows[0]["compatibility"]["authorization_source"] == "SECURITY_DOMAIN"
    assert "JOIN CX_DOMAIN_MEMBERS domain_member" in captured["sql"]
    assert "JOIN COLLAB_GROUP_MEMBERS self_member" in captured["sql"]
    assert captured["params"]["actor"] == "P1"


def test_legacy_message_compatibility_requires_governed_binding(monkeypatch):
    monkeypatch.setattr(security_domain_api, "_require", lambda _actor: None)
    monkeypatch.setattr(security_domain_api, "_text", lambda value, *_args, **_kwargs: value)
    monkeypatch.setattr(security_domain_api.connection, "execute_query", lambda *_args, **_kwargs: [])
    assert security_domain_api.list_legacy_collaboration_messages("P1", "G1") == []


def test_legacy_message_read_rechecks_domain_and_channel_without_disclosing_rows(monkeypatch):
    captured = {}
    monkeypatch.setattr(security_domain_api, "_require", lambda _actor: None)
    monkeypatch.setattr(security_domain_api.connection, "execute_query", lambda sql, params: captured.update(sql=sql, params=params) or [])
    rows = security_domain_api.list_legacy_collaboration_messages("P1", "G-PRIVATE", channel_id="CH-OTHER")
    assert rows == []
    assert "JOIN CX_DOMAIN_MEMBERS dm" in captured["sql"]
    assert "c.SECURITY_DOMAIN_ID=b.SECURITY_DOMAIN_ID" in captured["sql"]
    assert "dm.PRINCIPAL_ID=:actor" in captured["sql"]
    assert captured["params"] == {
        "actor": "P1", "group_id": "G-PRIVATE", "channel_id": "CH-OTHER", "limit": 100,
    }


def test_execution_group_listing_requires_domain_binding_and_marks_legacy(monkeypatch):
    captured = {}
    monkeypatch.setattr(security_domain_api, "_require", lambda actor, action: captured.update(actor=actor, action=action))
    monkeypatch.setattr(
        security_domain_api.connection,
        "execute_query",
        lambda sql, params: captured.update(sql=sql, params=params) or [{"group_id": "G1", "security_domain_id": "D1", "actor_type": "HUMAN"}],
    )
    rows = security_domain_api.list_execution_groups("P1")
    assert rows[0]["execution_group"] is True
    assert rows[0]["compatibility"]["deprecated_legacy_group"] is True
    assert captured["action"] == "collab.read"
    assert "CX_DOMAIN_BINDINGS" in captured["sql"]
    assert "CX_DOMAIN_MEMBERS" in captured["sql"]
    assert "SHARING_POLICY" not in captured["sql"].split("WHERE", 1)[-1]


def test_execution_group_access_fails_closed_without_current_domain(monkeypatch):
    monkeypatch.setattr(security_domain_api, "_require", lambda *_args: None)
    monkeypatch.setattr(security_domain_api.connection, "execute_query_one", lambda *_args, **_kwargs: None)
    with pytest.raises(PermissionError, match="Security Domain"):
        security_domain_api.assert_execution_group_access("P1", "G1")


def test_legacy_http_execution_routes_use_domain_aware_guard():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "visualization" / "server.py").read_text(encoding="utf-8")
    for method in ("_api_collab", "_api_collab_branch", "_api_collab_distribute_plan", "_api_collab_sync_context", "_api_collab_loop"):
        body = source.split(f"def {method}", 1)[1].split("\n    def ", 1)[0]
        assert "security_domain_api" in body
        assert "assert_execution_group_access" in body or method == "_api_collab"
