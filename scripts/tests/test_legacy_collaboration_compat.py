from lib import security_domain_api


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
