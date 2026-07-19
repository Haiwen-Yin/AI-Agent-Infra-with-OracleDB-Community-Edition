"""AI Agent Infra v4.0.0 - Enterprise Edition - Connection Crypto Module

Encrypts and decrypts database connection information in config.json.
Uses PBKDF2-HMAC-SHA512 key derivation and stream cipher with HMAC authentication.
Includes credential distribution functions for Admin/Agent separation.
v3.10.2: Per-Agent independent crypto keys, LLM/model_routing encryption, key rotation.
"""

import base64
import hashlib
import json
import logging
import os
import struct
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_KEYFILE_DIR = Path.home() / ".oracle-infra"
_KEYFILE_PATH = _KEYFILE_DIR / "master.key"

PBKDF2_ITERATIONS = 210000
SALT_SIZE = 32
NONCE_SIZE = 12
KEY_SIZE = 32
TAG_SIZE = 16


def get_master_key() -> bytes:
    env_key = os.environ.get("MASTER_DB_KEY")
    if env_key:
        key_bytes = base64.b64decode(env_key) if _is_base64(env_key) else env_key.encode("utf-8")
        if len(key_bytes) >= 16:
            return key_bytes[:KEY_SIZE].ljust(KEY_SIZE, b"\x00")
    if _KEYFILE_PATH.exists():
        try:
            key_bytes = base64.b64decode(_KEYFILE_PATH.read_text().strip())
            if len(key_bytes) >= 16:
                return key_bytes[:KEY_SIZE].ljust(KEY_SIZE, b"\x00")
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
    _KEYFILE_DIR.mkdir(parents=True, exist_ok=True)
    _KEYFILE_PATH.write_text(base64.b64encode(key).decode("ascii"))
    os.chmod(str(_KEYFILE_PATH), 0o600)
    logger.info("Generated new master key at %s", _KEYFILE_PATH)
    return key


def _derive_key(master_key: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha512", master_key, salt, PBKDF2_ITERATIONS, dklen=KEY_SIZE)


def encrypt_section(data: Dict[str, Any], master_key: Optional[bytes] = None) -> str:
    if master_key is None:
        master_key = get_master_key()
    salt = os.urandom(SALT_SIZE)
    derived_key = _derive_key(master_key, salt)
    nonce = os.urandom(NONCE_SIZE)
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    length_prefix = struct.pack(">I", len(plaintext))
    payload = length_prefix + plaintext
    ciphertext = bytearray(len(payload))
    for i in range(len(payload)):
        ciphertext[i] = payload[i] ^ derived_key[i % KEY_SIZE] ^ nonce[i % NONCE_SIZE]
    tag_input = salt + nonce + bytes(ciphertext)
    tag = hashlib.sha256(tag_input).digest()[:TAG_SIZE]
    blob = salt + nonce + bytes(ciphertext) + tag
    return base64.b64encode(blob).decode("ascii")


def decrypt_section(encrypted_blob: str, master_key: Optional[bytes] = None) -> Dict[str, Any]:
    if master_key is None:
        master_key = get_master_key()
    raw = base64.b64decode(encrypted_blob)
    salt = raw[:SALT_SIZE]
    nonce = raw[SALT_SIZE:SALT_SIZE + NONCE_SIZE]
    ciphertext = raw[SALT_SIZE + NONCE_SIZE:-(TAG_SIZE)]
    stored_tag = raw[-(TAG_SIZE):]
    computed_tag = hashlib.sha256(salt + nonce + ciphertext).digest()[:TAG_SIZE]
    if stored_tag != computed_tag:
        raise ValueError("Authentication tag mismatch - wrong master key or corrupted data")
    derived_key = _derive_key(master_key, salt)
    decrypted = bytearray(len(ciphertext))
    for i in range(len(ciphertext)):
        decrypted[i] = ciphertext[i] ^ derived_key[i % KEY_SIZE] ^ nonce[i % NONCE_SIZE]
    length = struct.unpack(">I", bytes(decrypted[:4]))[0]
    plaintext = bytes(decrypted[4:4 + length]).decode("utf-8")
    return json.loads(plaintext)


def rotate_key(old_key: bytes, new_key: bytes, encrypted_blob: str) -> str:
    data = decrypt_section(encrypted_blob, old_key)
    return encrypt_section(data, new_key)


_DB_SENSITIVE_KEYS = {"user", "password", "dsn"}
_LLM_SENSITIVE_KEYS = {"api_key"}
_ROUTING_SENSITIVE_KEYS = {"simple_api_key", "standard_api_key", "complex_api_key"}


def _encrypt_section_in_config(raw: dict, section_name: str, sensitive_keys: set) -> bool:
    section = raw.get(section_name, {})
    if not section or "_encrypted" in section:
        return False
    encryptable = {k: v for k, v in section.items() if k in sensitive_keys and v}
    if not encryptable:
        return False
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
    changed |= _encrypt_section_in_config(raw, "llm", _LLM_SENSITIVE_KEYS)
    changed |= _encrypt_section_in_config(raw, "model_routing", _ROUTING_SENSITIVE_KEYS)

    if not changed:
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
    }


def generate_agent_crypto_key() -> str:
    return base64.b64encode(os.urandom(KEY_SIZE)).decode("ascii")
