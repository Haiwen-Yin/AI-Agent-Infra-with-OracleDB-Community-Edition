"""Task-relevant projection of verified role-private management knowledge."""
from __future__ import annotations
import json
import re
from typing import Any
from . import content_security, native_agent_api


def retrieve(actor: str, agent: str, query: str, language: str = "zh", limit: int = 6) -> dict[str, Any]:
    source = native_agent_api.management_template_knowledge(actor, agent, language)
    terms = re.findall(r"[a-z0-9_]{2,40}|[\u4e00-\u9fff]{2,20}", query.lower())[:12]
    terms += [run[i:i+2] for run in re.findall(r"[\u4e00-\u9fff]{3,20}", query) for i in range(len(run)-1)]
    entries = []
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_en") and language == "zh" or key.endswith("_zh") and language != "zh":
                    continue
                visit(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, item in enumerate(value): visit(item, f"{path}[{index}]")
        elif isinstance(value, str) and value:
            score = sum(term in (path + " " + value).lower() for term in terms)
            if score:
                entries.append({"path": path, "content": value, "score": score,
                    "source_digest": native_agent_api._digest(source), "knowledge_version": source.get("knowledge_version")})
    visit(source, "")
    entries.sort(key=lambda item: (-item["score"], item["path"]))
    selected = entries[:max(1, min(limit, 12))]
    content_security.enforce(json.dumps(selected, ensure_ascii=False), "KNOWLEDGE")
    return {"status": "MATCHED" if selected else "NO_MATCH", "items": selected,
            "source": "VERIFIED_ROLE_KNOWLEDGE", "language": language}
