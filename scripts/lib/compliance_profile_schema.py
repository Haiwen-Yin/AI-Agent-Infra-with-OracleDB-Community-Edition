"""Strict mutation schema; historical template inspection remains separate."""
from __future__ import annotations

from typing import Any
from jsonschema import Draft202012Validator


def _enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": sorted({value for item in values for value in (item, item.upper())})}


CONTROL_PROPERTIES = {
    "database": _enum("gateway_only", "read_scoped", "least_privilege", "deny"),
    "network": _enum("allowlist", "isolated", "deny"),
    "secrets": _enum("broker_only", "deny"),
    "commands": _enum("approved_workspace", "allowlist", "deny"),
    "approval": _enum("required", "risk_based", "none"),
    "audit": _enum("immutable", "evidence_required", "standard", "extended"),
    "data": _enum("classified", "deny"),
    "export": _enum("approved", "deny"),
    "retention": _enum("evidence_required", "standard", "extended"),
    "tools": _enum("allowlist", "deny"),
    "skills": _enum("allowlist", "deny"),
    "classification_ceiling": _enum("public", "internal", "confidential", "restricted"),
    "allowed_tools": {"type": "array", "maxItems": 200, "uniqueItems": True,
                      "items": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"\S"}},
    "allowed_skills": {"type": "array", "maxItems": 200, "uniqueItems": True,
                       "items": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"\S"}},
}
for alias, canonical in {"database_access": "database", "network_egress": "network",
                         "approval_policy": "approval", "audit_retention": "audit"}.items():
    CONTROL_PROPERTIES[alias] = CONTROL_PROPERTIES[canonical]

PROFILE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1, "type": "integer"},
        "purpose": {"type": "string", "maxLength": 2000},
        "description": {"type": "string", "maxLength": 4000},
        "controls": {"type": "object", "additionalProperties": False, "properties": CONTROL_PROPERTIES},
        "locked_fields": {"type": "array", "uniqueItems": True, "maxItems": 64,
            "items": {"enum": ["controls", *CONTROL_PROPERTIES, *("controls." + key for key in CONTROL_PROPERTIES)]}},
    },
}
VALIDATOR = Draft202012Validator(PROFILE_SCHEMA)


def validate(content: Any) -> None:
    error = next(VALIDATOR.iter_errors(content), None)
    if error:
        # Never include the supplied value: this error can reach a browser or audit log.
        path = ".".join(str(part) for part in error.absolute_path) or "content"
        raise ValueError(f"Profile schema violation at {path} ({error.validator})")
    controls = content.get("controls", {})
    for alias, canonical in {"database_access": "database", "network_egress": "network",
                             "approval_policy": "approval", "audit_retention": "audit"}.items():
        if alias in controls and canonical in controls:
            raise ValueError(f"Profile schema has duplicate control aliases: {canonical}")
