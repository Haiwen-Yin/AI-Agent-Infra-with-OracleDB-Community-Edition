"""AI Agent Infra v4.0.1 - Enterprise Edition - Connection Crypto Module

Encrypts and decrypts database connection information in config.json.
Uses PBKDF2-HMAC-SHA512 key derivation and AES-256-GCM authenticated encryption.
Includes credential distribution functions for Admin/Agent separation.
Legacy v4.0.0 ciphertext is read only for controlled migration.
"""

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_KEYFILE_DIR = Path.home() / ".ai-agent-infra"
_KEYFILE_PATH = _KEYFILE_DIR / "master.key"
_LEGACY_KEYFILE_PATH = Path.home() / ".oracle-infra" / "master.key"

PBKDF2_ITERATIONS = 210000
SALT_SIZE = 32
NONCE_SIZE = 12
KEY_SIZE = 32
TAG_SIZE = 16
ENVELOPE_PREFIX = "aigcm:v1:"
ENVELOPE_AAD = b"ai-agent-infra:credential-envelope:v1"


def get_master_key() -> bytes:
    env_key = os.environ.get("MASTER_DB_KEY")
    if env_key:
        key_bytes = base64.b64decode(env_key) if _is_base64(env_key) else env_key.encode("utf-8")
        if len(key_bytes) >= 16:
            return key_bytes[:KEY_SIZE].ljust(KEY_SIZE, b"\x00")
    key_path = _KEYFILE_PATH if _KEYFILE_PATH.exists() else _LEGACY_KEYFILE_PATH
    if key_path.exists():
        try:
            key_bytes = base64.b64decode(key_path.read_text().strip())
            if len(key_bytes) >= 16:
                key = key_bytes[:KEY_SIZE].ljust(KEY_SIZE, b"\x00")
                if key_path == _LEGACY_KEYFILE_PATH:
                    _save_master_key(key)
                return key
        except Exception:
            pass
    return _generate_and_save_master_key()


def _is_base64(s: str) -> bool:
    try:
        base64.b64decode(s, validate=True)
        return True
    except Exception:
        return False


def _generate_and_save_master_key() -> bytes:
    key = os.urandom(KEY_SIZE)
    _save_master_key(key)
    logger.info("Generated new master key at %s", _KEYFILE_PATH)
    return key


def _save_master_key(key: bytes) -> None:
    _KEYFILE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(str(_KEYFILE_DIR), 0o700)
    temp_path = _KEYFILE_PATH.with_suffix(".tmp")
    temp_path.write_text(base64.b64encode(key).decode("ascii"))
    os.chmod(str(temp_path), 0o600)
    temp_path.replace(_KEYFILE_PATH)
    os.chmod(str(_KEYFILE_PATH), 0o600)


def _derive_key(master_key: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha512", master_key, salt, PBKDF2_ITERATIONS, dklen=KEY_SIZE)


def encrypt_section(data: Dict[str, Any], master_key: Optional[bytes] = None) -> str:
    if master_key is None:
        master_key = get_master_key()
    salt = os.urandom(SALT_SIZE)
    derived_key = _derive_key(master_key, salt)
    nonce = os.urandom(NONCE_SIZE)
    plaintext = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(derived_key).encrypt(nonce, plaintext, ENVELOPE_AAD)
    blob = salt + nonce + ciphertext
    return ENVELOPE_PREFIX + base64.b64encode(blob).decode("ascii")


def decrypt_section(encrypted_blob: str, master_key: Optional[bytes] = None) -> Dict[str, Any]:
    if master_key is None:
        master_key = get_master_key()
    if not encrypted_blob.startswith(ENVELOPE_PREFIX):
        return _decrypt_legacy_section(encrypted_blob, master_key)
    raw = base64.b64decode(encrypted_blob[len(ENVELOPE_PREFIX):], validate=True)
    if len(raw) < SALT_SIZE + NONCE_SIZE + TAG_SIZE:
        raise ValueError("Invalid AES-GCM credential envelope")
    salt = raw[:SALT_SIZE]
    nonce = raw[SALT_SIZE:SALT_SIZE + NONCE_SIZE]
    ciphertext = raw[SALT_SIZE + NONCE_SIZE:]
    derived_key = _derive_key(master_key, salt)
    try:
        plaintext = AESGCM(derived_key).decrypt(nonce, ciphertext, ENVELOPE_AAD)
    except InvalidTag as exc:
        raise ValueError("Credential authentication failed") from exc
    return json.loads(plaintext.decode("utf-8"))


def _decrypt_legacy_section(encrypted_blob: str, master_key: bytes) -> Dict[str, Any]:
    import struct

    raw = base64.b64decode(encrypted_blob, validate=True)
    if len(raw) < SALT_SIZE + NONCE_SIZE + TAG_SIZE + 4:
        raise ValueError("Invalid legacy credential envelope")
    salt = raw[:SALT_SIZE]
    nonce = raw[SALT_SIZE:SALT_SIZE + NONCE_SIZE]
    ciphertext = raw[SALT_SIZE + NONCE_SIZE:-TAG_SIZE]
    stored_tag = raw[-TAG_SIZE:]
    computed_tag = hashlib.sha256(salt + nonce + ciphertext).digest()[:TAG_SIZE]
    if not __import__("hmac").compare_digest(stored_tag, computed_tag):
        raise ValueError("Legacy credential checksum mismatch")
    derived_key = _derive_key(master_key, salt)
    decrypted = bytes(
        value ^ derived_key[index % KEY_SIZE] ^ nonce[index % NONCE_SIZE]
        for index, value in enumerate(ciphertext)
    )
    length = struct.unpack(">I", decrypted[:4])[0]
    if length != len(decrypted) - 4:
        raise ValueError("Invalid legacy credential length")
    plaintext = decrypted[4:].decode("utf-8")
    return json.loads(plaintext)


def migrate_encrypted_blob(encrypted_blob: str, master_key: Optional[bytes] = None) -> str:
    """Convert one legacy envelope to AES-GCM without changing its plaintext."""
    if encrypted_blob.startswith(ENVELOPE_PREFIX):
        decrypt_section(encrypted_blob, master_key)
        return encrypted_blob
    key = master_key or get_master_key()
    return encrypt_section(_decrypt_legacy_section(encrypted_blob, key), key)


def rotate_key(old_key: bytes, new_key: bytes, encrypted_blob: str) -> str:
    data = decrypt_section(encrypted_blob, old_key)
    return encrypt_section(data, new_key)


_DB_SENSITIVE_KEYS = {"user", "password", "dsn"}
_SECURITY_SENSITIVE_KEYS = {"secret_key"}
_LLM_SENSITIVE_KEYS = {"api_key"}
_ROUTING_SENSITIVE_KEYS = {"simple_api_key", "standard_api_key", "complex_api_key"}


def _encrypt_section_in_config(raw: dict, section_name: str, sensitive_keys: set) -> bool:
    section = raw.get(section_name, {})
    if not section:
        return False
    encryptable = {k: v for k, v in section.items() if k in sensitive_keys and v}
    if not encryptable:
        return False
    encrypted_blob = section.get("_encrypted")
    if encrypted_blob:
        encryptable = {**decrypt_section(encrypted_blob), **encryptable}
    encrypted = encrypt_section(encryptable)
    new_section = {}
    for k, v in section.items():
        if k not in sensitive_keys:
            new_section[k] = v
    new_section["_encrypted"] = encrypted
    raw[section_name] = new_section
    return True


def auto_encrypt_config(config_path: Path) -> bool:
    if not config_path.exists():
        return False
    try:
        with open(config_path, "r") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    changed = False
    changed |= _encrypt_section_in_config(raw, "database", _DB_SENSITIVE_KEYS)
    changed |= _encrypt_section_in_config(raw, "security", _SECURITY_SENSITIVE_KEYS)
    changed |= _encrypt_section_in_config(raw, "llm", _LLM_SENSITIVE_KEYS)
    changed |= _encrypt_section_in_config(raw, "model_routing", _ROUTING_SENSITIVE_KEYS)

    if not changed:
        try:
            os.chmod(str(config_path), 0o600)
        except OSError as e:
            logger.error("Failed to secure config permissions: %s", e)
        return False

    try:
        with open(config_path, "w") as f:
            json.dump(raw, f, indent=4, ensure_ascii=False)
        os.chmod(str(config_path), 0o600)
        logger.info("Auto-encrypted sensitive config sections in %s", config_path)
        return True
    except OSError as e:
        logger.error("Failed to write encrypted config: %s", e)
        return False


def _decrypt_section_in_config(section_raw: dict) -> dict:
    encrypted_blob = section_raw.get("_encrypted")
    if not encrypted_blob:
        return section_raw
    try:
        decrypted = decrypt_section(encrypted_blob)
        merged = dict(section_raw)
        for k, v in decrypted.items():
            if k not in ("_encrypted", "_key_source"):
                merged[k] = v
        return merged
    except Exception as e:
        logger.error("Failed to decrypt config section: %s", e)
        return section_raw


def decrypt_database_section(db_raw: dict) -> dict:
    return _decrypt_section_in_config(db_raw)


def decrypt_security_section(security_raw: dict) -> dict:
    """Resolve signing secrets while preserving non-sensitive security policy."""
    encrypted_blob = security_raw.get("_encrypted")
    if not encrypted_blob:
        return security_raw
    decrypted = decrypt_section(encrypted_blob)
    merged = dict(security_raw)
    for key, value in decrypted.items():
        if key not in ("_encrypted", "_key_source"):
            merged[key] = value
    return merged


def decrypt_llm_section(llm_raw: dict) -> dict:
    return _decrypt_section_in_config(llm_raw)


def decrypt_model_routing_section(mr_raw: dict) -> dict:
    return _decrypt_section_in_config(mr_raw)


def encrypt_credential_for_distribution(credential_data: Dict[str, Any], admin_token: str) -> Dict[str, str]:
    salt = os.urandom(SALT_SIZE)
    token_key = _derive_key(admin_token.encode("utf-8"), salt)
    encrypted = encrypt_section(credential_data, master_key=token_key)
    return {
        "credential_encrypted": encrypted,
        "salt": base64.b64encode(salt).decode("ascii"),
        "algorithm": "AES-256-GCM",
        "format_version": 1,
    }


def decrypt_credential_from_distribution(encrypted_credential: str, salt_b64: str, admin_token: str) -> Dict[str, Any]:
    salt = base64.b64decode(salt_b64)
    token_key = _derive_key(admin_token.encode("utf-8"), salt)
    return decrypt_section(encrypted_credential, master_key=token_key)


def save_agent_config(agent_id: str, credential_data: Dict[str, Any], config_path) -> None:
    config_path = Path(config_path) if not isinstance(config_path, Path) else config_path
    encrypted = encrypt_section(credential_data)
    config = {
        "agent_id": agent_id,
        "end_user": {
            "_encrypted": encrypted,
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    os.chmod(str(config_path), 0o600)
    logger.info("Saved encrypted agent config to %s", config_path)


def load_agent_config(config_path) -> Dict[str, Any]:
    config_path = Path(config_path) if not isinstance(config_path, Path) else config_path
    with open(config_path, "r") as f:
        raw = json.load(f)
    eu_section = raw.get("end_user", {})
    encrypted = eu_section.get("_encrypted")
    if encrypted:
        creds = decrypt_section(encrypted)
    else:
        creds = eu_section
    return {
        "agent_id": raw.get("agent_id"),
        "username": creds.get("username"),
        "password": creds.get("password"),
        "dsn": creds.get("dsn"),
        "host": creds.get("host"),
        "port": creds.get("port"),
        "dbname": creds.get("dbname"),
        "db_type": creds.get("db_type"),
    }


def generate_agent_crypto_key() -> str:
    return base64.b64encode(os.urandom(KEY_SIZE)).decode("ascii")
