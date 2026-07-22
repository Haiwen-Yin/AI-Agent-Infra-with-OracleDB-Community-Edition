"""AI Agent Infra v4.0.1 - Security Module Tests"""

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


def test_reversible_encryption():
    enc = ReversibleEncryption()
    plaintext = "Hello, World! This is a secret message."
    ciphertext = enc.encrypt(plaintext)
    decrypted = enc.decrypt(ciphertext)
    assert decrypted == plaintext
    print("PASS: test_reversible_encryption")


def test_password_hashing():
    pw = "MySecurePassword123!"
    hash_val, salt = hash_password(pw)
    assert verify_password(pw, hash_val, salt)
    assert not verify_password("wrong_password", hash_val, salt)
    print("PASS: test_password_hashing")


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_mask_email,
        test_mask_credit_card,
        test_mask_dict,
        test_reversible_encryption,
        test_password_hashing,
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
