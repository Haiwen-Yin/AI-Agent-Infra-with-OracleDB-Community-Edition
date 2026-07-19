#!/usr/bin/env python3
"""AI Agent Infra v4.0.0 - Config Encryption CLI Tool

Encrypts/decrypts/rotates/verifies sensitive sections in config.json.
Supports database, llm, and model_routing sections.

Usage:
    python -m tools.encrypt_config encrypt   [--config PATH]
    python -m tools.encrypt_config decrypt   [--config PATH] [--output PATH]
    python -m tools.encrypt_config rotate    [--config PATH]
    python -m tools.encrypt_config verify    [--config PATH]
    python -m tools.encrypt_config auto      [--config PATH]
"""

import argparse
import base64
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.connection_crypto import (
    encrypt_section, decrypt_section, rotate_key,
    auto_encrypt_config, get_master_key,
    _DB_SENSITIVE_KEYS, _LLM_SENSITIVE_KEYS, _ROUTING_SENSITIVE_KEYS,
)

_ALL_SECTIONS = {
    "database": _DB_SENSITIVE_KEYS,
    "llm": _LLM_SENSITIVE_KEYS,
    "model_routing": _ROUTING_SENSITIVE_KEYS,
}


def cmd_encrypt(args):
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r") as f:
        raw = json.load(f)

    encrypted_any = False
    for section_name, sensitive_keys in _ALL_SECTIONS.items():
        section = raw.get(section_name, {})
        if not section or "_encrypted" in section:
            continue
        sensitive = {k: v for k, v in section.items() if k in sensitive_keys and v}
        if not sensitive:
            continue
        encrypted = encrypt_section(sensitive)
        new_section = {k: v for k, v in section.items() if k not in sensitive_keys}
        new_section["_encrypted"] = encrypted
        if "_key_source" not in new_section:
            new_section["_key_source"] = "env:MASTER_DB_KEY"
        raw[section_name] = new_section
        print(f"  Encrypted {section_name}: {list(sensitive.keys())}")
        encrypted_any = True

    if not encrypted_any:
        print("No unencrypted sensitive fields found. Use 'rotate' to change key.")
        sys.exit(1)

    with open(config_path, "w") as f:
        json.dump(raw, f, indent=4, ensure_ascii=False)
    os.chmod(str(config_path), 0o600)
    print(f"Done. Encrypted config written to {config_path}")


def cmd_decrypt(args):
    config_path = Path(args.config)
    with open(config_path, "r") as f:
        raw = json.load(f)

    decrypted_any = False
    for section_name in _ALL_SECTIONS:
        section = raw.get(section_name, {})
        encrypted_blob = section.get("_encrypted")
        if not encrypted_blob:
            continue
        decrypted = decrypt_section(encrypted_blob)
        new_section = dict(section)
        del new_section["_encrypted"]
        new_section.pop("_key_source", None)
        new_section.update(decrypted)
        raw[section_name] = new_section
        print(f"  Decrypted {section_name}: {list(decrypted.keys())}")
        decrypted_any = True

    if not decrypted_any:
        print("No encrypted data found in any section.")
        sys.exit(1)

    output_path = Path(args.output) if args.output else config_path
    with open(output_path, "w") as f:
        json.dump(raw, f, indent=4, ensure_ascii=False)
    print(f"Done. Decrypted config written to {output_path}")
    print("WARNING: Sensitive credentials are now stored in plaintext!")


def cmd_rotate(args):
    config_path = Path(args.config)
    with open(config_path, "r") as f:
        raw = json.load(f)

    old_key = get_master_key()
    print("Enter new master key (base64-encoded, or press Enter to auto-generate):")
    new_key_input = input().strip()
    if new_key_input:
        new_key = base64.b64decode(new_key_input)
    else:
        new_key = os.urandom(32)
        print(f"Generated new key: {base64.b64encode(new_key).decode('ascii')}")
        print("Save this key! It will be needed to decrypt the config.")

    rotated_any = False
    for section_name in _ALL_SECTIONS:
        section = raw.get(section_name, {})
        encrypted_blob = section.get("_encrypted")
        if not encrypted_blob:
            continue
        new_blob = rotate_key(old_key, new_key, encrypted_blob)
        raw[section_name]["_encrypted"] = new_blob
        print(f"  Rotated {section_name}")
        rotated_any = True

    if not rotated_any:
        print("No encrypted data found. Use 'encrypt' first.")
        sys.exit(1)

    with open(config_path, "w") as f:
        json.dump(raw, f, indent=4, ensure_ascii=False)
    print(f"Done. Rotated encryption key in {config_path}")


def cmd_verify(args):
    config_path = Path(args.config)
    with open(config_path, "r") as f:
        raw = json.load(f)

    found_any = False
    for section_name in _ALL_SECTIONS:
        section = raw.get(section_name, {})
        encrypted_blob = section.get("_encrypted")
        if not encrypted_blob:
            continue
        found_any = True
        try:
            decrypted = decrypt_section(encrypted_blob)
            keys = list(decrypted.keys())
            masked = {k: "****" if k in ("password", "api_key") else v for k, v in decrypted.items()}
            print(f"  {section_name}: OK ({keys}) -> {masked}")
        except ValueError as e:
            print(f"  {section_name}: FAILED - {e}")

    if not found_any:
        print("No encrypted sections found.")


def cmd_auto(args):
    config_path = Path(args.config)
    if auto_encrypt_config(config_path):
        print(f"Auto-encrypted sensitive sections in {config_path}")
    else:
        print(f"No changes needed (already encrypted or no sensitive fields) in {config_path}")


def main():
    parser = argparse.ArgumentParser(description="Config Encryption CLI Tool")
    parser.add_argument("command", choices=["encrypt", "decrypt", "rotate", "verify", "auto"],
                        help="Command to execute")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent.parent.parent / "config.json"),
                        help="Path to config.json")
    parser.add_argument("--output", help="Output path for decrypt command")
    args = parser.parse_args()

    commands = {
        "encrypt": cmd_encrypt,
        "decrypt": cmd_decrypt,
        "rotate": cmd_rotate,
        "verify": cmd_verify,
        "auto": cmd_auto,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
