"""An interrupted initializer resumes exact completed actions without replay."""
from pathlib import Path

import pytest

from lib import deployment_orchestrator as deployment


def prepared(monkeypatch, tmp_path):
    source = tmp_path / "base.sql"
    source.write_text("SELECT 1")
    actions = [deployment.ManifestAction("base-01", "BASE_SCHEMA", source)]
    executed = []
    monkeypatch.setattr(deployment, "release_baseline", lambda *_: {"required_terminal_migration": "99.sql"})
    monkeypatch.setattr(deployment, "release_version", lambda *_: "4.5.1")
    monkeypatch.setattr(deployment, "_read_config", lambda *_: {})
    monkeypatch.setattr(deployment, "_resolve_sensitive_config", lambda value: value)
    monkeypatch.setattr(deployment, "_database_config", lambda *_: {})
    monkeypatch.setattr(deployment, "_activate_runtime_config", lambda *_: None)
    monkeypatch.setattr(deployment, "manifest", lambda *_: actions)
    monkeypatch.setattr(deployment, "preflight", lambda *_a, **kwargs: {
        "passed": True, "checks": [{"code": "TARGET_EMPTY", "state": "PASS", "detail": {"table_count": 0}}] if kwargs["require_empty"] else [],
    })
    monkeypatch.setattr(deployment, "_execute_action", lambda *_: executed.append("executed"))
    monkeypatch.setattr(deployment, "_set_bootstrap_admin", lambda *_: None)
    monkeypatch.setattr(deployment, "_bootstrap_admin_hash", lambda *_: "synthetic-hash")
    monkeypatch.setattr(deployment, "_deployment_database_status", lambda *_: {})
    def interrupted(*_):
        raise RuntimeError("Synthetic interruption before migration")
    monkeypatch.setattr(deployment, "_migration_apply", interrupted)
    values = {"database": "oracle", "edition": "community", "config_path": tmp_path / "config.json",
              "root": tmp_path, "run_id": "DEPLOY_RESUME", "bootstrap_admin_password": "synthetic-test-only"}
    return actions, executed, values


def test_completed_actions_and_empty_preflight_survive_migration_interruption(monkeypatch, tmp_path):
    actions, executed, values = prepared(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        deployment.run("INITIALIZE", **values)
    journal = deployment.DeploymentJournal(tmp_path, "DEPLOY_RESUME")
    before = journal.load()
    assert before["completed_actions"] == {actions[0].key: actions[0].digest}
    assert before["initial_preflight"]["checks"][0]["detail"]["table_count"] == 0
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        deployment.run("RESUME", **values)
    assert executed == ["executed"]
    after = journal.load()
    assert after["completed_actions"] == before["completed_actions"]
    assert after["initial_preflight"] == before["initial_preflight"]


def test_changed_plan_cannot_overwrite_or_resume_the_original_journal(monkeypatch, tmp_path):
    actions, executed, values = prepared(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError):
        deployment.run("INITIALIZE", **values)
    journal = deployment.DeploymentJournal(tmp_path, "DEPLOY_RESUME")
    before = journal.path.read_bytes()
    actions[0].path.write_text("SELECT 2")
    with pytest.raises(deployment.DeploymentError, match="plan changed"):
        deployment.run("RESUME", **values)
    assert executed == ["executed"]
    assert journal.path.read_bytes() == before
