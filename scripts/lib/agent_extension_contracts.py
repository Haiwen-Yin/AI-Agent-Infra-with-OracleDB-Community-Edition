"""Bounded data contracts shared by registered Agent integrations."""

import hashlib
import json
import re
import uuid
from urllib.parse import urlsplit
import urllib.request

from jsonschema import Draft202012Validator


def row(value):
    return {str(key).lower(): item for key, item in dict(value or {}).items()}


def identifier(prefix):
    return prefix + "_" + uuid.uuid4().hex


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def bounded_json(value, *, maximum=262144, depth=24):
    if len(canonical(value).encode("utf-8")) > maximum:
        raise ValueError("Integration payload exceeds its size limit")
    def inspect(item, remaining):
        if remaining < 0:
            raise ValueError("Integration payload exceeds its nesting limit")
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                inspect(nested, remaining - 1)
        elif isinstance(item, list):
            for nested in item:
                inspect(nested, remaining - 1)
    inspect(value, depth)
    return value


def validate_schema(schema, value=None, *, check_value=True):
    if not isinstance(schema, dict):
        raise ValueError("An object JSON Schema is required")
    bounded_json(schema)
    def references(item):
        if isinstance(item, dict):
            if "$ref" in item and not str(item["$ref"]).startswith("#"):
                raise ValueError("External schema references are not permitted")
            for nested in item.values():
                references(nested)
        elif isinstance(item, list):
            for nested in item:
                references(nested)
    references(schema)
    Draft202012Validator.check_schema(schema)
    if check_value:
        bounded_json(value)
        Draft202012Validator(schema).validate(value)


def registered_url(value):
    parsed = urlsplit(str(value or ""))
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment or parsed.query
            or any(ord(char) < 32 for char in str(value))):
        raise ValueError("A registered HTTP(S) endpoint without embedded credentials is required")
    if parsed.hostname.lower() in {"169.254.169.254", "metadata.google.internal"}:
        raise ValueError("Infrastructure metadata endpoints are not permitted")
    return str(value).rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Registered integration requests must not redirect")


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def safe_key(value, *, maximum=128):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0," + str(maximum - 1) + "}", value):
        raise ValueError("Invalid integration identifier")
    return value
