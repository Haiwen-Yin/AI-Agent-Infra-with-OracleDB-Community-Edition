from pathlib import Path
from typing import Any

import pytest

from lib import platform_agent_pool


class RegistryConnection:
    DATABASE_DIALECT = "postgresql"

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.commands = {item[0]: dict(
            command_id=f"PCMD_{item[0]}_V1", command_key=item[0], version=1,
            status="PUBLISHED", risk_level=item[1], execution_mode=item[2],
            parameter_schema=platform_agent_pool._json(item[5]), example_text=item[3], localized_metadata='{}',
            expiry_seconds=900, executor_state="ENABLED" if item[2] in {"DIRECT_READ", "GOVERNED_EXECUTOR"} else "DISABLED",
        ) for item in platform_agent_pool.COMMAND_SEEDS}

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        if "FROM CX_PLATFORM_COMMANDS" in sql:
            return self.commands.get(str(params.get("key") or ""))
        if "COUNT(*) AS CNT" in sql:
            return {"cnt": 0}
        return None

    def execute_query(self, sql: str, params: dict[str, Any] | None = None):
        if "FROM CX_PLATFORM_COMMANDS c" in sql:
            return [dict(value) for value in self.commands.values()]
        return []

    query_one = execute_query_one
    query = execute_query

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        self.executed.append((sql, dict(params or {})))
        if "INSERT INTO CX_PLATFORM_COMMANDS(" in sql:
            self.commands[str(params["key"])] = {"command_id": str(params["id"]), "command_key": str(params["key"])}
        return 1

    def execute_transaction_callback(self, work):
        return work(self)


@pytest.fixture
def service(monkeypatch):
    db = RegistryConnection()
    monkeypatch.setattr(platform_agent_pool, "connection", db)
    monkeypatch.setattr(
        platform_agent_pool.identity_api, "effective_access",
        lambda *_args, **_kwargs: {"decision": "ALLOW"},
    )
    monkeypatch.setattr(platform_agent_pool.identity_api, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(platform_agent_pool.identity_api, "_audit_tx", lambda *_args, **_kwargs: None)
    return db


def test_registry_contains_help_and_accurate_execution_boundaries():
    keys = {item[0]: item for item in platform_agent_pool.COMMAND_SEEDS}
    assert keys["HELP"][2] == "DIRECT_READ"
    assert keys["AGENT_DRAIN"][2] == "GOVERNED_EXECUTOR"
    assert keys["AGENT_QUARANTINE"][2] == "PROPOSAL_ONLY"
    assert keys["TEMPLATE_PUBLISH_PROPOSE"][1] == "HIGH_RISK_CHANGE"
    source = (Path(__file__).resolve().parents[1] / "lib" / "platform_agent_pool.py").read_text(encoding="utf-8")
    seeder = source.split("def ensure_platform_command_registry", 1)[1].split("def list_command_catalog", 1)[0]
    assert ":execution_mode" in seeder
    assert ":mode" not in seeder


def test_registry_is_idempotent(service):
    service.commands.clear()
    service.executed.clear()
    result = platform_agent_pool.ensure_platform_command_registry()
    assert result["seeded"] == len(platform_agent_pool.COMMAND_SEEDS)
    result = platform_agent_pool.ensure_platform_command_registry()
    assert result["seeded"] == 0
    service.executed.clear()
    assert not any("INSERT INTO CX_PLATFORM_COMMANDS" in sql for sql, _ in service.executed)


def test_catalog_and_help_are_filtered_by_administration_channel(service):
    catalog = platform_agent_pool.list_command_catalog("admin", query="AGENT")
    assert {item["command_key"] for item in catalog["items"]} >= {"AGENT_STATUS_READ", "AGENT_DRAIN", "AGENT_QUARANTINE"}
    with pytest.raises(platform_agent_pool.AgentPoolError):
        platform_agent_pool.list_command_catalog("admin", channel_id="CH_OTHER")
    help_result = platform_agent_pool.command_help("admin", "AGENT_DRAIN")
    assert help_result["item"]["command_key"] == "AGENT_DRAIN"
    with pytest.raises(platform_agent_pool.AgentPoolError, match="UNKNOWN_PLATFORM_COMMAND"):
        platform_agent_pool.command_help("admin", "NOT_REAL")


def test_command_contract_rejects_missing_parameters_and_reason(service):
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        platform_agent_pool.identity_api, "create_action_card",
        lambda *_args, **_kwargs: {"action_id": "ACT_TEST"},
    )
    with pytest.raises(platform_agent_pool.AgentPoolError, match="COMMAND_PARAMETER_REQUIRED"):
        platform_agent_pool.create_command("admin", "AGENT_DRAIN", {}, {}, "DEFAULT", "prepare maintenance")
    with pytest.raises(platform_agent_pool.AgentPoolError, match="COMMAND_REASON_REQUIRED"):
        platform_agent_pool.create_command("admin", "HEALTH_READ", {}, {}, "DEFAULT", "no")
    monkey.undo()


def test_channel_and_api_contracts_exist():
    root = Path(__file__).resolve().parents[2]
    web_path = root / "web_app.py" if (root / "web_app.py").exists() else root / "shared" / "web_app.py"
    if not web_path.is_file():
        web_path = root / "scripts" / "web_app.py"
    web = web_path.read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx" if (root / "web" / "src" / "App.tsx").exists() else root / "shared" / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    lib_root = root / "lib" if (root / "lib").is_dir() else root / "shared" / "lib"
    if not lib_root.is_dir():
        lib_root = root / "scripts" / "lib"
    native = (lib_root / "native_agent_api.py").read_text(encoding="utf-8")
    runtime = (lib_root / "native_runtime.py").read_text(encoding="utf-8")
    assert "/api/platform/admin-commands/catalog" in web
    assert "/api/platform/admin-commands/help" in web
    assert "/platform HELP" in ui
    assert "commandCatalog" in ui
    assert "response_language: lang" in ui
    assert 'open={isAdministrationChannel && showCommandPanel}' in ui
    assert 'title={text("平台命令", "Platform commands")}' in ui
    assert 'showTransientFeedback(' in ui
    assert "platform_command_help" in native
    assert "platform_command_result" in native
    assert "_platform_command_help_markdown" in runtime
    assert "_platform_command_result_markdown" in runtime
    assert "response_language: str = Field(default=\"\", max_length=8)" in web
