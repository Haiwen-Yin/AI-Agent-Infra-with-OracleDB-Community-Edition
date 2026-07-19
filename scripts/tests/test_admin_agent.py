"""AI Agent Infra v4.0.0 - Admin/Agent Separation Tests

Tests for admin token management, credential distribution,
agent registration via admin, recovery codes, agent recovery,
and agent_config encryption.
"""

import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.agent_api import (
    register_agent, get_agent,
    generate_admin_token, verify_admin_token,
    register_agent_via_admin,
    generate_recovery_codes, verify_recovery_code,
    recover_agent_via_admin,
)
from lib.connection_crypto import (
    encrypt_credential_for_distribution,
    decrypt_credential_from_distribution,
    save_agent_config,
    load_agent_config,
    encrypt_section,
    decrypt_section,
)
from lib.connection import close_pool

TEST_AGENT = "admin-test-agent"
ADMIN_TOKEN = None


def test_generate_admin_token():
    global ADMIN_TOKEN
    ADMIN_TOKEN = generate_admin_token()
    assert ADMIN_TOKEN is not None
    assert ADMIN_TOKEN.startswith("AT_")
    assert len(ADMIN_TOKEN) > 10
    print(f"PASS: test_generate_admin_token (token={ADMIN_TOKEN[:16]}...)")


def test_verify_admin_token():
    assert verify_admin_token(ADMIN_TOKEN)
    assert not verify_admin_token("AT_invalid_token_12345")
    assert not verify_admin_token("")
    assert not verify_admin_token("wrong_prefix_12345")
    print("PASS: test_verify_admin_token")


def test_verify_admin_token_after_rotate():
    global ADMIN_TOKEN
    new_token = generate_admin_token()
    assert verify_admin_token(new_token)
    assert not verify_admin_token(ADMIN_TOKEN)
    ADMIN_TOKEN = new_token
    print("PASS: test_verify_admin_token_after_rotate")


def test_credential_distribution_encrypt_decrypt():
    cred_data = {
        "username": "TEST_AGENT_EU",
        "password": "test_password_123",
        "dsn": "localhost:1521/test",
    }
    token = "AT_test_distribution_token"
    encrypted = encrypt_credential_for_distribution(cred_data, token)
    assert "credential_encrypted" in encrypted
    assert "salt" in encrypted

    decrypted = decrypt_credential_from_distribution(
        encrypted["credential_encrypted"],
        encrypted["salt"],
        token,
    )
    assert decrypted["username"] == "TEST_AGENT_EU"
    assert decrypted["password"] == "test_password_123"
    assert decrypted["dsn"] == "localhost:1521/test"
    print("PASS: test_credential_distribution_encrypt_decrypt")


def test_credential_distribution_wrong_token():
    cred_data = {"username": "X", "password": "Y", "dsn": "Z"}
    encrypted = encrypt_credential_for_distribution(cred_data, "AT_correct_token")
    try:
        decrypt_credential_from_distribution(
            encrypted["credential_encrypted"],
            encrypted["salt"],
            "AT_wrong_token",
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("PASS: test_credential_distribution_wrong_token")


def test_save_load_agent_config():
    cred_data = {
        "username": "CONFIG_TEST_EU",
        "password": "config_test_pwd",
        "dsn": "localhost:1521/test",
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        config_path = f.name

    try:
        save_agent_config("config-test-agent", cred_data, config_path)
        with open(config_path) as f:
            raw = json.load(f)
        assert "end_user" in raw
        assert "_encrypted" in raw["end_user"]
        assert "password" not in json.dumps(raw)

        loaded = load_agent_config(config_path)
        assert loaded["agent_id"] == "config-test-agent"
        assert loaded["username"] == "CONFIG_TEST_EU"
        assert loaded["password"] == "config_test_pwd"
        assert loaded["dsn"] == "localhost:1521/test"
        print("PASS: test_save_load_agent_config")
    finally:
        os.unlink(config_path)


def test_register_agent_via_admin():
    result = register_agent_via_admin(
        agent_id=TEST_AGENT,
        agent_name="Admin Test Agent",
        admin_token=ADMIN_TOKEN,
        agent_type="BUSINESS",
        description="Test agent for admin registration",
    )
    assert result is not None
    assert result["agent_id"] == TEST_AGENT
    assert "end_user" in result
    assert "credential_encrypted" in result["end_user"]
    assert "salt" in result["end_user"]

    agent = get_agent(TEST_AGENT)
    assert agent is not None
    assert agent["agent_name"] == "Admin Test Agent"
    print(f"PASS: test_register_agent_via_admin (agent={TEST_AGENT})")


def test_register_agent_via_admin_invalid_token():
    result = register_agent_via_admin(
        agent_id="should-not-work",
        agent_name="Invalid Token Agent",
        admin_token="AT_invalid_token",
    )
    assert result is None
    print("PASS: test_register_agent_via_admin_invalid_token")


def test_full_registration_and_local_save():
    result = register_agent_via_admin(
        agent_id="full-flow-agent",
        agent_name="Full Flow Agent",
        admin_token=ADMIN_TOKEN,
    )
    assert result is not None

    decrypted = decrypt_credential_from_distribution(
        result["end_user"]["credential_encrypted"],
        result["end_user"]["salt"],
        ADMIN_TOKEN,
    )
    assert "username" in decrypted
    assert "password" in decrypted
    assert "dsn" in decrypted

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        config_path = f.name

    try:
        save_agent_config("full-flow-agent", decrypted, config_path)
        loaded = load_agent_config(config_path)
        assert loaded["username"] == decrypted["username"]
        assert loaded["password"] == decrypted["password"]
        assert loaded["dsn"] == decrypted["dsn"]
        print("PASS: test_full_registration_and_local_save")
    finally:
        os.unlink(config_path)


RECOVERY_AGENT = "recovery-test-agent"
RECOVERY_CODES = None


def test_recovery_codes_generated_on_register():
    global RECOVERY_CODES
    token = generate_admin_token()
    result = register_agent_via_admin(
        agent_id=RECOVERY_AGENT,
        agent_name="Recovery Test Agent",
        admin_token=token,
    )
    assert result is not None
    assert "recovery_codes" in result
    codes = result["recovery_codes"]
    assert len(codes) == 8
    for code in codes:
        assert code.startswith("RC-")
        assert len(code.split("-")) == 4
    RECOVERY_CODES = codes
    print(f"PASS: test_recovery_codes_generated_on_register (codes={len(codes)})")


def test_verify_recovery_code_valid():
    assert RECOVERY_CODES is not None, "No recovery codes from register"
    code = RECOVERY_CODES[0]
    ok = verify_recovery_code(RECOVERY_AGENT, code)
    assert ok, "First recovery code should be valid"
    print("PASS: test_verify_recovery_code_valid")


def test_verify_recovery_code_used():
    code = RECOVERY_CODES[0]
    ok = verify_recovery_code(RECOVERY_AGENT, code)
    assert not ok, "Recovery code should be one-time use only"
    print("PASS: test_verify_recovery_code_used")


def test_verify_recovery_code_second():
    code = RECOVERY_CODES[1]
    ok = verify_recovery_code(RECOVERY_AGENT, code)
    assert ok, "Second recovery code should still be valid"
    print("PASS: test_verify_recovery_code_second")


def test_verify_recovery_code_invalid():
    ok = verify_recovery_code(RECOVERY_AGENT, "RC-0000-0000-FAKE")
    assert not ok, "Invalid recovery code should fail"
    print("PASS: test_verify_recovery_code_invalid")


def test_recover_agent_via_admin():
    token = generate_admin_token()
    code = RECOVERY_CODES[2]
    from lib.connection import execute
    execute(
        "UPDATE AGENT_REGISTRY SET LAST_SEEN_AT = CAST(SYSTIMESTAMP AS TIMESTAMP) - NUMTODSINTERVAL(1, 'HOUR') WHERE AGENT_ID = :aid",
        {"aid": RECOVERY_AGENT},
    )
    result = recover_agent_via_admin(
        agent_id=RECOVERY_AGENT,
        recovery_code=code,
        admin_token=token,
    )
    assert result is not None
    assert result.get("recovered") is True
    assert "end_user" in result
    assert "credential_encrypted" in result["end_user"]
    print(f"PASS: test_recover_agent_via_admin (agent={RECOVERY_AGENT})")


def test_recover_agent_same_code_fails():
    token = generate_admin_token()
    code = RECOVERY_CODES[2]
    result = recover_agent_via_admin(
        agent_id=RECOVERY_AGENT,
        recovery_code=code,
        admin_token=token,
    )
    assert result is None, "Used recovery code should fail"
    print("PASS: test_recover_agent_same_code_fails")


def test_recover_agent_invalid_token():
    code = RECOVERY_CODES[3]
    result = recover_agent_via_admin(
        agent_id=RECOVERY_AGENT,
        recovery_code=code,
        admin_token="AT_invalid_token",
    )
    assert result is None
    print("PASS: test_recover_agent_invalid_token")


def test_register_returns_recovery_codes():
    token = generate_admin_token()
    result = register_agent_via_admin(
        agent_id="rc-return-test-agent",
        agent_name="RC Return Test",
        admin_token=token,
    )
    assert result is not None
    assert "recovery_codes" in result
    assert len(result["recovery_codes"]) == 8
    print("PASS: test_register_returns_recovery_codes")


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_generate_admin_token,
        test_verify_admin_token,
        test_verify_admin_token_after_rotate,
        test_credential_distribution_encrypt_decrypt,
        test_credential_distribution_wrong_token,
        test_save_load_agent_config,
        test_register_agent_via_admin,
        test_register_agent_via_admin_invalid_token,
        test_full_registration_and_local_save,
        test_recovery_codes_generated_on_register,
        test_verify_recovery_code_valid,
        test_verify_recovery_code_used,
        test_verify_recovery_code_second,
        test_verify_recovery_code_invalid,
        test_recover_agent_via_admin,
        test_recover_agent_same_code_fails,
        test_recover_agent_invalid_token,
        test_register_returns_recovery_codes,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    close_pool()
    print(f"\nAdmin/Agent Separation Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
