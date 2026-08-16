"""Focused v4.4.6 identity and Portal admission contracts."""

from lib import identity_api


def test_registration_profile_normalizes_and_validates_contact_fields(monkeypatch):
    monkeypatch.setattr(identity_api, "_required_query", lambda *_args, **_kwargs: [
        {"field_key": "display_name", "field_state": "REQUIRED", "version": 3},
        {"field_key": "email", "field_state": "OPTIONAL", "version": 3},
        {"field_key": "mobile", "field_state": "OPTIONAL", "version": 3},
    ])
    value = identity_api._normalize_registration_profile(
        "  Alice  ", "Alice@Example.COM", "+86 (138) 0011-2233",
    )
    assert value == {
        "display_name": "Alice",
        "email": "alice@example.com",
        "mobile": "+8613800112233",
    }


def test_registration_profile_enforces_required_and_disabled_policy(monkeypatch):
    monkeypatch.setattr(identity_api, "_required_query", lambda *_args, **_kwargs: [
        {"field_key": "display_name", "field_state": "REQUIRED"},
        {"field_key": "email", "field_state": "DISABLED"},
        {"field_key": "mobile", "field_state": "REQUIRED"},
    ])
    try:
        identity_api._normalize_registration_profile("", "bad", "")
    except identity_api.IdentityError:
        pass
    else:
        raise AssertionError("required registration fields must be enforced")
    value = identity_api._normalize_registration_profile("Alice", "", "+8613800112233")
    assert value["email"] == ""


def test_human_registration_token_consumption_is_purpose_bound_and_atomic(monkeypatch):
    monkeypatch.setattr(identity_api, "_secret_digest", lambda value, purpose: "digest:" + purpose)
    calls = []

    class Connection:
        @staticmethod
        def execute_query(sql, params):
            calls.append(("query", sql, params))
            return [{"token_id": "HRT-1"}]

        @staticmethod
        def execute(sql, params):
            calls.append(("update", sql, params))
            return 1

    monkeypatch.setattr(identity_api, "connection", Connection())
    assert identity_api._consume_human_registration_token("raw") == "HRT-1"
    assert "PURPOSE = 'HUMAN_REGISTRATION'" in calls[0][1]
    assert "USED_COUNT < MAX_USES" in calls[1][1]


def test_portal_page_lease_conflict_is_read_only(monkeypatch):
    class Tx:
        def query_one(self, sql, params):
            if "CX_PORTAL_CONNECTIONS" in sql:
                return {"connection_id": "PC-1"}
            if "CX_PORTAL_PAGE_LEASES" in sql:
                return {"lease_id": "PPL-1", "page_instance_digest": "other", "fencing_token": 1}
            return None

        def execute(self, *_args, **_kwargs):
            return 1

    monkeypatch.setattr(identity_api.connection, "execute_transaction_callback", lambda callback: callback(Tx()))
    monkeypatch.setattr(identity_api, "_secret_digest", lambda value, purpose: "current")
    try:
        identity_api.acquire_portal_page_lease("session", "page")
    except identity_api.IdentityError as exc:
        assert str(exc) == "Portal page is in use"
    else:
        raise AssertionError("a second page must not acquire the operation lease")


def test_database_read_only_contract_is_exact_and_not_username_based(monkeypatch):
    queries = []

    class Connection:
        DATABASE_DIALECT = "postgresql"

        @staticmethod
        def execute_query_one(sql, params):
            queries.append((sql, params))
            return {"override_id": "OV-1"} if params["principal_id"] == "principal-read" else None

    monkeypatch.setattr(identity_api, "connection", Connection())
    assert identity_api.is_global_read_only_principal("principal-read") is True
    assert identity_api.is_global_read_only_principal("readonly") is False
    assert all("RESOURCE_ACTION = 'system.runtime.global_readonly'" in sql for sql, _ in queries)
