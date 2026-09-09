"""Bounded deterministic content inspection; findings never grant authority."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from urllib.parse import unquote
from typing import Any

MAX_BYTES = 256 * 1024
STAGES = frozenset({"USER_INPUT", "AGENT_PROMPT", "KNOWLEDGE", "TOOL_RESULT", "OUTPUT"})
RULES = (
    ("PRIVATE_KEY", "DENY", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ("PROVIDER_CREDENTIAL", "DENY", r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})\b"),
    ("CREDENTIAL_ASSIGNMENT", "DENY", r'''(?i)\b(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)\s*[=:]\s*["']?[A-Za-z0-9_+/=-]{16,}'''),
    ("INSTRUCTION_OVERRIDE", "WARN", r"(?i)(?:ignore|disregard|override)\s+(?:all\s+)?(?:previous|system|developer|prior)(?:\s+(?:system|developer))?\s+(?:instructions?|prompts?|rules?)|忽略.{0,8}(?:系统|先前|之前|开发者).{0,8}(?:指令|提示|规则)"),
    ("SECRET_EXFILTRATION", "WARN", r"(?i)(?:send|upload|export|reveal|print).{0,60}(?:api.?key|password|access.?token|private.?key)|(?:发送|上传|导出|泄露|显示).{0,30}(?:密钥|口令|密码|访问令牌)"),
    ("AUTHORITY_IMPERSONATION", "WARN", r"(?i)(?:i am|act as|you are now).{0,20}(?:root|system administrator)|(?:我是|扮演|现在是).{0,12}(?:超级管理员|系统管理员)"),
    ("AUDIT_BYPASS", "WARN", r"(?i)(?:disable|bypass|delete).{0,20}(?:audit|security checks)|(?:关闭|绕过|删除).{0,12}(?:审计|安全检查)"),
)
COMPILED_RULES = tuple((key, decision, re.compile(pattern)) for key, decision, pattern in RULES)
RULESET_DIGEST = hashlib.sha256(json.dumps(RULES, separators=(",", ":")).encode()).hexdigest()


class ContentDenied(ValueError):
    def __init__(self, result: dict[str, Any]):
        self.result = result
        super().__init__("Content security check rejected the request (" + result["code"] + ")")


def scan(content: str, stage: str) -> dict[str, Any]:
    if stage not in STAGES or not isinstance(content, str):
        raise ValueError("Unsupported content scan stage or format")
    raw = content.encode("utf-8")
    result: dict[str, Any] = {"stage": stage, "ruleset_digest": RULESET_DIGEST,
        "content_digest": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw),
        "decision": "ALLOW", "code": "CONTENT_CHECKED", "findings": [], "transforms": []}
    if len(raw) > MAX_BYTES:
        return {**result, "decision": "DENY", "code": "CONTENT_TOO_LARGE"}
    normalized = "".join(c for c in unicodedata.normalize("NFKC", content) if unicodedata.category(c) != "Cf")
    variants = [("NFKC_FORMAT", normalized)]
    decoded = unquote(normalized)
    if decoded != normalized:
        variants.append(("PERCENT", decoded))
    # Decode only explicit bounded base64 tokens, once; no recursive expansion.
    for match in list(re.finditer(r"(?i)(?:base64:|base64,)\s*([A-Za-z0-9+/=]{16,8192})", normalized))[:8]:
        try:
            variants.append(("BASE64", base64.b64decode(match[1], validate=True).decode("utf-8")))
        except (ValueError, UnicodeError):
            result["findings"].append({"rule": "UNPARSED_ENCODING", "decision": "WARN"})
    for transform, text in variants:
        result["transforms"].append(transform)
        for key, decision, pattern in COMPILED_RULES:
            match = pattern.search(text)
            if match:
                result["findings"].append({"rule": key, "decision": decision,
                                           "transform": transform, "start": match.start(), "end": match.end()})
    decisions = {item["decision"] for item in result["findings"]}
    result["decision"] = "DENY" if "DENY" in decisions else "WARN" if decisions else "ALLOW"
    result["code"] = "CONTENT_DENIED" if "DENY" in decisions else "CONTENT_REVIEW" if decisions else "CONTENT_CHECKED"
    return result


def enforce(content: str, stage: str) -> dict[str, Any]:
    result = scan(content, stage)
    if result["decision"] == "DENY":
        raise ContentDenied(result)
    return result


def inspect_messages(messages: list[dict[str, Any]]) -> None:
    if not isinstance(messages, list) or not messages or len(messages) > 100:
        raise ValueError("Model messages must be a bounded nonempty list")
    if len(json.dumps(messages, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ContentDenied({"code": "CONTENT_TOO_LARGE"})
    for message in messages:
        content = message.get("content")
        if not isinstance(content, str):
            raise ContentDenied({"code": "CONTENT_FORMAT_UNSUPPORTED"})
        role = message.get("role")
        enforce(content, "AGENT_PROMPT" if role in {"system", "developer"} else "TOOL_RESULT" if role == "tool" else "OUTPUT" if role == "assistant" else "USER_INPUT")
