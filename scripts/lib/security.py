"""AI Agent Infra v4.0.0 - Enterprise Edition - Security Module

Data masking, context-aware masking, reversible encryption, and config encryption.
"""

import re
import hashlib
import os
import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DataMaskingService:
    SENSITIVE_PATTERNS = {
        "credit_card": re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "jwt_token": re.compile(r"eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*"),
        "api_key": re.compile(r"(?i)(?:secret|key|token)[A-Za-z0-9_-]{16,}"),
        "email": re.compile(r"([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"),
        "ip_address": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b"),
        "phone": re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    }

    MASK_RULES = {
        "email": lambda m: f"{'*' * len(m.group(1))}@{m.group(2)}",
        "phone": lambda m: m.group()[:3] + "***-" + m.group()[-4:],
        "credit_card": lambda m: "****-****-****-" + m.group()[-4:],
        "ssn": lambda m: "***-**-" + m.group()[-4:],
        "api_key": lambda m: m.group()[:4] + "..." + m.group()[-4:],
        "ip_address": lambda m: ".".join(["***" if i != 3 else d for i, d in enumerate(m.group().split("."))]),
        "jwt_token": lambda m: "eyJ..." + m.group()[-16:] if len(m.group()) > 20 else "[JWT_MASKED]",
    }

    CONTEXT_LEVELS = {
        "LOGGING": {"email", "phone", "credit_card", "ssn", "api_key", "jwt_token"},
        "DEBUGGING": {"email", "phone", "credit_card", "ssn", "api_key", "jwt_token", "ip_address"},
        "ANALYTICS": {"credit_card", "ssn", "api_key", "jwt_token"},
        "SHARING": {"email", "phone", "credit_card", "ssn", "api_key", "jwt_token", "ip_address"},
    }

    def __init__(self, context_level: str = "LOGGING"):
        self.context_level = context_level

    PATTERN_ORDER = ["credit_card", "ssn", "jwt_token", "api_key", "email", "ip_address", "phone"]

    def mask_text(self, text: str) -> str:
        if not text:
            return text
        masked = text
        active_patterns = self.CONTEXT_LEVELS.get(self.context_level, set())
        for pname in self.PATTERN_ORDER:
            if pname not in active_patterns:
                continue
            pattern = self.SENSITIVE_PATTERNS.get(pname)
            rule = self.MASK_RULES.get(pname)
            if pattern and rule:
                masked = pattern.sub(rule, masked)
        return masked

    def mask_dict(self, data: Dict[str, Any], parent_key: str = "") -> Dict[str, Any]:
        if not isinstance(data, dict):
            return data
        sensitive_keys = {"password", "token", "secret", "key", "credential", "ssn", "email", "auth"}
        masked = {}
        for k, v in data.items():
            is_sensitive = any(s in k.lower() for s in sensitive_keys)
            if isinstance(v, str):
                if is_sensitive:
                    result = self.mask_text(v)
                    if result == v and len(v) > 0:
                        result = "***MASKED***"
                    masked[k] = result
                else:
                    masked[k] = v
            elif isinstance(v, dict):
                masked[k] = self.mask_dict(v, parent_key=k)
            elif isinstance(v, list):
                masked[k] = [self.mask_dict(i, k) if isinstance(i, dict) else
                             (self.mask_text(i) if is_sensitive and isinstance(i, str) else i)
                             for i in v]
            else:
                masked[k] = v
        return masked

    def mask_json(self, json_string: str) -> str:
        try:
            data = json.loads(json_string)
            if isinstance(data, dict):
                return json.dumps(self.mask_dict(data), ensure_ascii=False)
            elif isinstance(data, list):
                return json.dumps([self.mask_dict(i) if isinstance(i, dict) else i for i in data],
                                  ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
        return self.mask_text(json_string)


class ReversibleEncryption:
    def __init__(self, key: Optional[bytes] = None):
        self._key = key or os.urandom(32)

    def encrypt(self, plaintext: str) -> str:
        iv = os.urandom(16)
        dk = hashlib.pbkdf2_hmac("sha256", self._key, iv, 100000)
        data = plaintext.encode("utf-8")
        length_prefix = len(data).to_bytes(4, "big")
        payload = length_prefix + data
        encrypted = bytes(payload[i] ^ dk[i % len(dk)] ^ iv[i % len(iv)] for i in range(len(payload)))
        return base64.b64encode(iv + encrypted).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        raw = base64.b64decode(ciphertext)
        iv = raw[:16]
        encrypted = raw[16:]
        dk = hashlib.pbkdf2_hmac("sha256", self._key, iv, 100000)
        decrypted = bytes(encrypted[i] ^ dk[i % len(dk)] ^ iv[i % len(iv)] for i in range(len(encrypted)))
        length = int.from_bytes(decrypted[:4], "big")
        return decrypted[4:4 + length].decode("utf-8")

    def rotate_key(self, new_key: bytes, encrypted_values: List[str]) -> List[str]:
        old_key = self._key
        plaintexts = []
        for val in encrypted_values:
            self._key = old_key
            plaintexts.append(self.decrypt(val))
        self._key = new_key
        return [self.encrypt(pt) for pt in plaintexts]


def hash_password(password: str, salt: Optional[bytes] = None, iterations: int = 100000) -> Tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return pw_hash.hex(), salt.hex()


def verify_password(password: str, stored_hash: str, salt_hex: str, iterations: int = 100000) -> bool:
    salt = bytes.fromhex(salt_hex)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return pw_hash.hex() == stored_hash


default_masking_service = DataMaskingService()


class ConfigEncryption:
    PBKDF2_ITERATIONS = 210000
    SALT_SIZE = 32
    KEY_SIZE = 32
    NONCE_SIZE = 12
    TAG_SIZE = 16

    def __init__(self, master_key: Optional[bytes] = None):
        self._master_key = master_key or self._resolve_master_key()

    @staticmethod
    def _resolve_master_key() -> bytes:
        from .connection_crypto import get_master_key
        return get_master_key()

    def _derive_key(self, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha512", self._master_key, salt, self.PBKDF2_ITERATIONS, dklen=self.KEY_SIZE)

    def encrypt(self, plaintext: str) -> str:
        salt = os.urandom(self.SALT_SIZE)
        dk = self._derive_key(salt)
        nonce = os.urandom(self.NONCE_SIZE)
        data = plaintext.encode("utf-8")
        length_prefix = len(data).to_bytes(4, "big")
        payload = length_prefix + data
        ciphertext = bytearray(len(payload))
        for i in range(len(payload)):
            ciphertext[i] = payload[i] ^ dk[i % self.KEY_SIZE] ^ nonce[i % self.NONCE_SIZE]
        tag_input = salt + nonce + bytes(ciphertext)
        tag = hashlib.sha256(tag_input).digest()[:self.TAG_SIZE]
        blob = salt + nonce + bytes(ciphertext) + tag
        return base64.b64encode(blob).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        raw = base64.b64decode(ciphertext)
        salt = raw[:self.SALT_SIZE]
        nonce = raw[self.SALT_SIZE:self.SALT_SIZE + self.NONCE_SIZE]
        encrypted = raw[self.SALT_SIZE + self.NONCE_SIZE:-(self.TAG_SIZE)]
        stored_tag = raw[-(self.TAG_SIZE):]
        computed_tag = hashlib.sha256(salt + nonce + encrypted).digest()[:self.TAG_SIZE]
        if stored_tag != computed_tag:
            raise ValueError("Authentication tag mismatch - wrong master key or corrupted data")
        dk = self._derive_key(salt)
        decrypted = bytearray(len(encrypted))
        for i in range(len(encrypted)):
            decrypted[i] = encrypted[i] ^ dk[i % self.KEY_SIZE] ^ nonce[i % self.NONCE_SIZE]
        length = int.from_bytes(bytes(decrypted[:4]), "big")
        return bytes(decrypted[4:4 + length]).decode("utf-8")

    def rotate_key(self, new_master_key: bytes, encrypted_values: List[str]) -> List[str]:
        old_key = self._master_key
        plaintexts = []
        for val in encrypted_values:
            self._master_key = old_key
            plaintexts.append(self.decrypt(val))
        self._master_key = new_master_key
        return [self.encrypt(pt) for pt in plaintexts]
