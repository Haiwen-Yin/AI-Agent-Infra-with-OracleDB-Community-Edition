from lib import native_agent_api


def test_llm_listing_requires_platform_management(monkeypatch):
    calls = []
    monkeypatch.setattr(
        native_agent_api.identity_api, "effective_access",
        lambda *_args, **_kwargs: {"decision": "DENY"},
    )
    monkeypatch.setattr(native_agent_api.connection, "execute_query", lambda *args, **kwargs: calls.append(args))
    try:
        native_agent_api.list_llm_profiles("agent-a")
    except PermissionError:
        pass
    else:
        raise AssertionError("LLM profile listing must require platform.manage")
    assert not calls


def test_llm_listing_never_selects_secret_columns(monkeypatch):
    queries = []
    monkeypatch.setattr(
        native_agent_api.identity_api, "effective_access",
        lambda *_args, **_kwargs: {"decision": "ALLOW"},
    )
    monkeypatch.setattr(native_agent_api.connection, "execute_query", lambda sql, params: queries.append(sql) or [])
    native_agent_api.list_llm_profiles("admin")
    assert queries
    assert all("API_KEY_CIPHER" not in sql.upper() for sql in queries)
