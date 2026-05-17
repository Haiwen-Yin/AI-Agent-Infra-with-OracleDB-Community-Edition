"""Oracle Memory System v2.0.0 - Security Module Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.security import (
    DataMaskingService, ReversibleEncryption,
    hash_password, verify_password, default_masking_service
)


def test_mask_email():
    svc = DataMaskingService("LOGGING")
    result = svc.mask_text("Contact user@example.com for details")
    assert "****@example.com" in result
    assert "user@" not in result
    print("PASS: test_mask_email")


def test_mask_phone():
    svc = DataMaskingService("LOGGING")
    result = svc.mask_text("Call 555-123-4567 now")
    assert "555***-4567" in result
    print("PASS: test_mask_phone")


def test_mask_credit_card():
    svc = DataMaskingService("LOGGING")
    result = svc.mask_text("Card 4111111111111111 charged")
    assert "****-****-****-1111" in result
    print("PASS: test_mask_credit_card")


def test_mask_dict():
    svc = DataMaskingService("LOGGING")
    data = {"username": "john", "password": "secret123", "token": "eyJabc.def.ghi"}
    result = svc.mask_dict(data)
    assert result["username"] == "john"
    assert result["password"] != "secret123"
    print("PASS: test_mask_dict")


def test_context_levels():
    for level in ["LOGGING", "DEBUGGING", "ANALYTICS", "SHARING"]:
        svc = DataMaskingService(level)
        result = svc.mask_text("test 192.168.1.1 email@test.com")
        print(f"PASS: test_context_level_{level}")


def test_encryption_roundtrip():
    enc = ReversibleEncryption()
    plaintext = "Hello, World! This is a secret message."
    ciphertext = enc.encrypt(plaintext)
    decrypted = enc.decrypt(ciphertext)
    assert decrypted == plaintext
    print("PASS: test_encryption_roundtrip")


def test_key_rotation():
    enc = ReversibleEncryption()
    vals = [enc.encrypt(f"secret_{i}") for i in range(3)]
    new_key = os.urandom(32)
    rotated = enc.rotate_key(new_key, vals)
    enc2 = ReversibleEncryption(key=new_key)
    for i, rv in enumerate(rotated):
        assert enc2.decrypt(rv) == f"secret_{i}"
    print("PASS: test_key_rotation")


def test_password_hashing():
    pw = "MySecurePassword123!"
    hash_val, salt = hash_password(pw)
    assert verify_password(pw, hash_val, salt)
    assert not verify_password("wrong_password", hash_val, salt)
    print("PASS: test_password_hashing")


def test_password_with_custom_iterations():
    pw = "test"
    hash_val, salt = hash_password(pw, iterations=10000)
    assert verify_password(pw, hash_val, salt, iterations=10000)
    print("PASS: test_password_custom_iterations")


def test_default_masking_service():
    result = default_masking_service.mask_text("admin@company.com")
    assert "admin@" not in result
    print("PASS: test_default_masking_service")


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_mask_email,
        test_mask_phone,
        test_mask_credit_card,
        test_mask_dict,
        test_context_levels,
        test_encryption_roundtrip,
        test_key_rotation,
        test_password_hashing,
        test_password_with_custom_iterations,
        test_default_masking_service,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    print(f"\nSecurity Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
