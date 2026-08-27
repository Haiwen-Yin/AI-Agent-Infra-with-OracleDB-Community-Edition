from pathlib import Path

import pytest

from lib import native_agent_api


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MODE = (ROOT / "build-manifest.json").is_file() and not (ROOT / "shared").is_dir()
LIB_ROOT = ROOT / ("scripts/lib" if PACKAGE_MODE else "shared/lib")
WEB_APP_PATH = ROOT / ("scripts/web_app.py" if PACKAGE_MODE else "shared/web_app.py")
UI_PATH = ROOT / ("web/src/App.tsx" if PACKAGE_MODE else "shared/web/src/App.tsx")


class FakeTransaction:
    def __init__(self, blockers=()):
        self.blockers = set(blockers)
        self.executed = []

    def query_one(self, query, params):
        if "FROM CX_LLM_PROVIDER_PROFILES" in query:
            return {"PROFILE_ID": params["id"], "PROFILE_KEY": "qwen3.6", "STATUS": "ACTIVE"}
        blocker_queries = {
            "CX_PORTAL_LLM_POLICIES": "PORTAL_DEFAULT",
            "CX_PORTAL_LLM_ALLOWLIST": "PORTAL_ALLOWLIST",
            "CX_NATIVE_AGENTS": "ACTIVE_NATIVE_AGENT",
            "CX_NATIVE_PROVISION_REQUESTS": "PENDING_AGENT_REQUEST",
        }
        for marker, blocker in blocker_queries.items():
            if marker in query:
                return {"CNT": 1 if blocker in self.blockers else 0}
        raise AssertionError(f"unexpected query: {query}")

    def execute(self, query, params):
        self.executed.append((query, params))


def _authorize(monkeypatch, transaction):
    monkeypatch.setattr(
        native_agent_api.identity_api,
        "effective_access",
        lambda *_args, **_kwargs: {"decision": "ALLOW"},
    )
    monkeypatch.setattr(
        native_agent_api.connection,
        "execute_transaction_callback",
        lambda callback: callback(transaction),
    )
    monkeypatch.setattr(native_agent_api, "_audit", lambda *args, **kwargs: None)


def test_retire_llm_profile_reports_stable_blocker_codes(monkeypatch):
    transaction = FakeTransaction({"PORTAL_DEFAULT", "ACTIVE_NATIVE_AGENT"})
    _authorize(monkeypatch, transaction)

    with pytest.raises(native_agent_api.LLMProfileInUse) as caught:
        native_agent_api.retire_llm_profile("admin", "LLM_QWEN3_6", "remove obsolete model")

    assert caught.value.blockers == ("PORTAL_DEFAULT", "ACTIVE_NATIVE_AGENT")
    assert str(caught.value) == "LLM_PROFILE_IN_USE:PORTAL_DEFAULT,ACTIVE_NATIVE_AGENT"
    assert transaction.executed == []


def test_retire_unreferenced_llm_profile_revokes_secret(monkeypatch):
    transaction = FakeTransaction()
    _authorize(monkeypatch, transaction)

    result = native_agent_api.retire_llm_profile(
        "admin", "LLM_QWEN3_6", "remove obsolete model"
    )

    assert result == {
        "profile_id": "LLM_QWEN3_6",
        "profile_key": "qwen3.6",
        "status": "RETIRED",
        "secret_present": False,
    }
    statement, params = transaction.executed[0]
    assert "API_KEY_CIPHER=NULL" in statement
    assert params["id"] == "LLM_QWEN3_6"


def test_llm_probe_accepts_provider_namespace_but_rejects_wrong_model():
    assert native_agent_api._llm_model_matches("qwen3.8-27b", "qwen/qwen3.8-27b")
    assert native_agent_api._llm_model_matches("deepseek-v4-flash", "deepseek-v4-flash-0731")
    assert native_agent_api._llm_model_matches("vendor/deepseek-v4-flash", "deepseek/deepseek-v4-flash-2026-07-31")
    assert not native_agent_api._llm_model_matches("deepseek-v4-flash", "deepseek-v4-flash-other")
    assert not native_agent_api._llm_model_matches("qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled", "qwen/qwen3.8-27b")
    assert not native_agent_api._llm_model_matches("qwen3.8-27b", "")
    assert "LLM provider probe failed" in (LIB_ROOT / "native_agent_api.py").read_text(encoding="utf-8")


def test_async_forms_do_not_use_react_current_target_after_await():
    source = UI_PATH.read_text(encoding="utf-8")
    assert "event.currentTarget.reset()" not in source
    assert "LLM_PROFILE_IN_USE:" in source
    assert "def probe_saved_llm_profile" in (LIB_ROOT / "native_agent_api.py").read_text(encoding="utf-8")
    assert "/api/llm-provider-profiles/{profile_id}/probe" in WEB_APP_PATH.read_text(encoding="utf-8")
    profiles = source.split("function LLMProviderProfilesPanel", 1)[1].split("function PlatformOperationsPage", 1)[0]
    assert "const probe = async" in profiles
    assert "LLM provider returned a different model" in (LIB_ROOT / "native_agent_api.py").read_text(encoding="utf-8")
    assert "refreshProfileHealth" in source
