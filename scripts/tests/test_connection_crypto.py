"""Authenticated credential encryption tests."""

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import struct
import sys

import pytest

MODULE_PATH = os.path.join(os.path.dirname(__file__), "..", "lib", "connection_crypto.py")
SPEC = importlib.util.spec_from_file_location("connection_crypto_under_test", MODULE_PATH)
crypto = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(crypto)

ENVELOPE_PREFIX = crypto.ENVELOPE_PREFIX
KEY_SIZE = crypto.KEY_SIZE
NONCE_SIZE = crypto.NONCE_SIZE
SALT_SIZE = crypto.SALT_SIZE
TAG_SIZE = crypto.TAG_SIZE
_derive_key = crypto._derive_key
decrypt_credential_from_distribution = crypto.decrypt_credential_from_distribution
decrypt_section = crypto.decrypt_section
decrypt_security_section = crypto.decrypt_security_section
encrypt_credential_for_distribution = crypto.encrypt_credential_for_distribution
encrypt_section = crypto.encrypt_section
auto_encrypt_config = crypto.auto_encrypt_config
load_agent_config = crypto.load_agent_config
migrate_encrypted_blob = crypto.migrate_encrypted_blob
save_agent_config = crypto.save_agent_config


TEST_KEY = bytes(range(KEY_SIZE))


def _legacy_encrypt(data, key):
    salt = bytes(range(SALT_SIZE))
    nonce = bytes(range(NONCE_SIZE))
    derived_key = _derive_key(key, salt)
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    payload = struct.pack(">I", len(plaintext)) + plaintext
    ciphertext = bytes(
        value ^ derived_key[index % KEY_SIZE] ^ nonce[index % NONCE_SIZE]
        for index, value in enumerate(payload)
    )
    tag = hashlib.sha256(salt + nonce + ciphertext).digest()[:TAG_SIZE]
    return base64.b64encode(salt + nonce + ciphertext + tag).decode("ascii")


def test_aes_gcm_round_trip():
    source = {"user": "agent_1", "password": "secret", "db_type": "pg"}
    encrypted = encrypt_section(source, TEST_KEY)

    assert encrypted.startswith(ENVELOPE_PREFIX)
    assert decrypt_section(encrypted, TEST_KEY) == source


def test_aes_gcm_rejects_tampering():
    encrypted = encrypt_section({"password": "secret"}, TEST_KEY)
    raw = bytearray(base64.b64decode(encrypted[len(ENVELOPE_PREFIX):]))
    raw[-1] ^= 1
    tampered = ENVELOPE_PREFIX + base64.b64encode(raw).decode("ascii")

    with pytest.raises(ValueError, match="authentication failed"):
        decrypt_section(tampered, TEST_KEY)


def test_legacy_envelope_migrates_to_aes_gcm():
    source = {"dsn": "db.example/agent", "username": "agent"}
    legacy = _legacy_encrypt(source, TEST_KEY)

    assert decrypt_section(legacy, TEST_KEY) == source
    migrated = migrate_encrypted_blob(legacy, TEST_KEY)
    assert migrated.startswith(ENVELOPE_PREFIX)
    assert decrypt_section(migrated, TEST_KEY) == source


def test_distribution_rejects_wrong_admin_token():
    encrypted = encrypt_credential_for_distribution(
        {"username": "agent", "password": "secret"}, "AT_correct"
    )

    assert encrypted["algorithm"] == "AES-256-GCM"
    assert encrypted["format_version"] == 1
    with pytest.raises(ValueError):
        decrypt_credential_from_distribution(
            encrypted["credential_encrypted"], encrypted["salt"], "AT_wrong"
        )


def test_agent_config_preserves_database_type(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_DB_KEY", base64.b64encode(TEST_KEY).decode("ascii"))
    config_path = tmp_path / "agent_config.json"
    source = {
        "username": "business_agent",
        "password": "secret",
        "dsn": "db.example/service",
        "db_type": "yashandb",
    }

    save_agent_config("AGENT_1", source, config_path)
    loaded = load_agent_config(config_path)

    assert loaded["agent_id"] == "AGENT_1"
    assert loaded["db_type"] == "yashandb"
    assert loaded["username"] == "business_agent"


def test_auto_encrypts_security_secret_and_preserves_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_DB_KEY", base64.b64encode(TEST_KEY).decode("ascii"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "security": {
            "secret_key": "session-signing-secret",
            "session_timeout": 300,
            "max_login_attempts": 5,
        }
    }))

    assert auto_encrypt_config(config_path) is True

    stored = json.loads(config_path.read_text())
    assert "secret_key" not in stored["security"]
    assert stored["security"]["_encrypted"].startswith(ENVELOPE_PREFIX)
    assert stored["security"]["session_timeout"] == 300
    assert stored["security"]["max_login_attempts"] == 5
    resolved = decrypt_security_section(stored["security"])
    assert resolved["secret_key"] == "session-signing-secret"
    assert resolved["session_timeout"] == 300
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_auto_secures_permissions_when_config_is_already_encrypted(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_DB_KEY", base64.b64encode(TEST_KEY).decode("ascii"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "security": {"_encrypted": encrypt_section({"secret_key": "secret"}, TEST_KEY)}
    }))
    config_path.chmod(0o644)

    assert auto_encrypt_config(config_path) is False
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_auto_reencrypts_section_when_plaintext_is_added_to_envelope(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_DB_KEY", base64.b64encode(TEST_KEY).decode("ascii"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "security": {
            "_encrypted": encrypt_section({"secret_key": "old-secret"}, TEST_KEY),
            "secret_key": "replacement-secret",
            "session_timeout": 300,
        }
    }))

    assert auto_encrypt_config(config_path) is True
    stored = json.loads(config_path.read_text())
    assert "secret_key" not in stored["security"]
    assert decrypt_security_section(stored["security"])["secret_key"] == "replacement-secret"


def test_security_decryption_fails_closed_on_tampering(monkeypatch):
    monkeypatch.setenv("MASTER_DB_KEY", base64.b64encode(TEST_KEY).decode("ascii"))
    encrypted = encrypt_section({"secret_key": "secret"}, TEST_KEY)
    raw = bytearray(base64.b64decode(encrypted[len(ENVELOPE_PREFIX):]))
    raw[-1] ^= 1
    tampered = ENVELOPE_PREFIX + base64.b64encode(raw).decode("ascii")

    with pytest.raises(ValueError, match="authentication failed"):
        decrypt_security_section({"_encrypted": tampered})


def test_cli_verify_masks_security_secret(tmp_path):
    secret = "must-not-appear-in-cli-output"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "security": {"_encrypted": encrypt_section({"secret_key": secret}, TEST_KEY)}
    }))
    env = os.environ.copy()
    env["MASTER_DB_KEY"] = base64.b64encode(TEST_KEY).decode("ascii")

    result = subprocess.run(
        [sys.executable, str(MODULE_PATH.rsplit("/lib/", 1)[0] + "/tools/encrypt_config.py"),
         "verify", "--config", str(config_path)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    assert secret not in result.stdout
    assert "'secret_key': '****'" in result.stdout


def test_cli_decrypt_output_is_owner_only(tmp_path):
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "decrypted.json"
    config_path.write_text(json.dumps({
        "security": {"_encrypted": encrypt_section({"secret_key": "secret"}, TEST_KEY)}
    }))
    env = os.environ.copy()
    env["MASTER_DB_KEY"] = base64.b64encode(TEST_KEY).decode("ascii")

    subprocess.run(
        [sys.executable, str(MODULE_PATH.rsplit("/lib/", 1)[0] + "/tools/encrypt_config.py"),
         "decrypt", "--config", str(config_path), "--output", str(output_path)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )

    assert output_path.stat().st_mode & 0o777 == 0o600
