"""Regression contracts for the v4.4.10 no-external-Agent bootstrap path."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import migration_runner
from lib import deployment_orchestrator, identity_api


def _layout() -> tuple[Path, Path, bool]:
    tests_parent = Path(__file__).resolve().parents[1]
    packaged = tests_parent.name == "scripts"
    package_root = tests_parent.parent if packaged else tests_parent.parent
    return tests_parent, package_root, packaged


def _load_bootstrap_cli():
    runtime_root, _package_root, packaged = _layout()
    path = runtime_root / "bootstrap_deployment_agent.py" if packaged else runtime_root / "scripts" / "bootstrap_deployment_agent.py"
    spec = importlib.util.spec_from_file_location("cx_bootstrap_cli_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _packaged_database(root: Path) -> str:
    manifest = root / "build-manifest.json"
    if not manifest.is_file():
        return "oracle"
    return str(json.loads(manifest.read_text(encoding="utf-8"))["database"]["key"])


def test_baseline_declares_v410_terminal_knowledge_context():
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "build-manifest.json"
    if manifest_path.is_file():
        package = json.loads(manifest_path.read_text(encoding="utf-8"))
        databases = (str(package["database"]["key"]),)
    else:
        databases = ("oracle", "pg", "yashandb")
    for database in databases:
        baseline = deployment_orchestrator.release_baseline(database, root)
        assert baseline["version"] == "4.4.10"
        assert baseline["deployment"] == "bootstrap-deployment-agent"
        assert baseline["required_terminal_migration"] == "59_v4_4_10_knowledge_graph_context.sql"


def test_release_version_rejects_requested_package_mismatch():
    root = Path(__file__).resolve().parents[2]
    database = _packaged_database(root)
    assert deployment_orchestrator.release_version(database, root, "4.4.10") == "4.4.10"
    with pytest.raises(deployment_orchestrator.DeploymentError, match="does not match"):
        deployment_orchestrator.release_version(database, root, "4.3.7")


def test_public_release_selector_routes_v410_to_complete_chain(monkeypatch):
    expected = ["55.sql", "56.sql", "57.sql", "58.sql", "59.sql"]
    monkeypatch.setattr(migration_runner, "_v410_script_names", lambda *_args: expected)
    assert migration_runner.release_script_names("4.4.10", "oracle", Path("config.json"), "enterprise") == expected
    with pytest.raises(ValueError, match="unsupported package bootstrap version"):
        migration_runner.release_script_names("9.9.9", "oracle", Path("config.json"), "enterprise")


def test_initial_admin_password_uses_identity_argon2id_policy(monkeypatch):
    captured = {}
    def hash_password(value):
        captured["password"] = value
        return "$argon2id$test"
    monkeypatch.setattr(identity_api, "hash_password_argon2id", hash_password)
    hashed = deployment_orchestrator._bootstrap_admin_hash("Correct-Horse-Battery-2026")
    assert captured["password"] == "Correct-Horse-Battery-2026"
    assert hashed == "$argon2id$test"
    assert identity_api.verify_password_hash("placeholder_change_me", "SHA256:placeholder_change_me")[0] is False


def test_noninteractive_password_file_must_be_private(tmp_path):
    cli = _load_bootstrap_cli()
    password_file = tmp_path / "admin-password"
    password_file.write_text("Correct-Horse-Battery-2026\n", encoding="utf-8")
    password_file.chmod(0o644)
    with pytest.raises(deployment_orchestrator.DeploymentError, match="0600"):
        cli._initial_admin_password("initialize", password_file)
    password_file.chmod(0o600)
    assert cli._initial_admin_password("initialize", password_file) == "Correct-Horse-Battery-2026"


def test_bootstrap_requires_recoverable_backup_evidence(tmp_path):
    root = Path(__file__).resolve().parents[2]
    with pytest.raises(deployment_orchestrator.DeploymentError, match="backup evidence"):
        deployment_orchestrator._verify_backup_evidence(None, root)
    evidence = tmp_path / "backup.json"
    evidence.write_text(json.dumps({
        "recoverable": True,
        "created_at": "2026-08-24T00:00:00Z",
        "backup_ref": "customer-backup-reference",
    }), encoding="utf-8")
    assert deployment_orchestrator._verify_backup_evidence(evidence, root) == {
        "status": "VERIFIED", "reference": "backup.json",
    }


def test_bootstrap_evidence_contains_identity_not_plaintext_password():
    source = (Path(__file__).resolve().parents[1] / "lib" / "deployment_orchestrator.py").read_text(encoding="utf-8")
    postflight = source.split('_record_evidence(journal.run_id, "POSTFLIGHT"', 1)[1]
    assert '"initial_admin": admin' in postflight
    assert '"bootstrap_admin_password"' not in postflight
    assert '"password_hash"' not in postflight


def test_first_run_wizard_keeps_llm_optional_and_generates_session_secret():
    runtime_root, package_root, packaged = _layout()
    wizard_path = runtime_root / "config_wizard.sh" if packaged else runtime_root / "scripts" / "config_wizard.sh"
    wizard = wizard_path.read_text(encoding="utf-8")
    assert "LLM API URL (leave empty to configure after bootstrap)" in wizard
    assert 'LLM_MODEL=""' in wizard
    assert "secrets.token_urlsafe(48)" in wizard
    if packaged:
        example = json.loads((package_root / "config.example.json").read_text(encoding="utf-8"))
        assert example["security"]["secret_key"] == "<SESSION_SECRET>"
    else:
        build = (package_root / "build.py").read_text(encoding="utf-8")
        assert '"secret_key": "<SESSION_SECRET>"' in build
