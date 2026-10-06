"""Domain-authorized metadata-first discovery and exact-content loading."""
import json
from . import connection, identity_api, continuity_work as work, skill_api, tool_registry
from .agent_extension_contracts import row, canonical, digest, bounded_json


def _authority(tx, actor, domain, family):
    work._authorize(tx, actor, domain, write=False)
    from .continuity_bindings import _transport
    transport = _transport.get()
    if transport is not None:
        from .agent_gateway_api import _authenticate_access_token_digest
        scope = "skills.read" if family == "SKILL" else "tools.read"
        credential = _authenticate_access_token_digest(transport["token_digest"], actor, transport["instance_id"], scope, operation=scope, query_one=tx.query_one)
        if not credential or credential["security_domain_id"] != domain or int(credential["fencing_token"]) != int(transport["fencing_token"]):
            raise PermissionError("The original directory credential was revoked or fenced")
    access = identity_api.effective_access(actor, "skills.read" if family == "SKILL" else "tools.read", resource={"security_domain_id": domain})
    if access.get("decision") != "ALLOW":
        raise PermissionError("Directory permission denied")
    return access


def _skill_visible(actor, skill, access):
    return (skill.get("owned_by_agent") == actor or "ALL" in access.get("scopes", []) or skill.get("visibility") == "PUBLIC")


def _metadata(family, item):
    if family == "SKILL":
        content = {key: item.get(key) for key in ("skill_name", "skill_version", "text_content", "parameters", "dependencies", "resource_checksum")}
        label, version = item.get("skill_name") or item.get("title"), str(item.get("skill_version") or "")
        description = item.get("skill_description") or ""
    else:
        content = {key: item.get(key) for key in ("tool_name", "tool_version", "input_schema", "output_schema", "mcp_exposed", "status")}
        label, version, description = item.get("tool_name"), str(item.get("tool_version") or ""), item.get("description") or ""
    bounded_json(content, maximum=262144)
    return {"family": family, "entity_id": str(item.get("entity_id") if family == "SKILL" else item.get("tool_id")),
            "name": str(label or ""), "version": version, "description": str(description)[:1000], "content_digest": digest(content)}, content


def search(actor, domain, family, query="", *, after="", limit=20):
    if family not in {"SKILL", "TOOL"} or not isinstance(query, str) or len(query) > 200 or not 1 <= int(limit) <= 50:
        raise ValueError("Invalid directory query")
    def perform(tx):
        access = _authority(tx, actor, domain, family)
        params = {"page_limit": int(limit) + 1}
        conditions = []
        if family == "SKILL":
            key, field = "e.ENTITY_ID", "e.TITLE"
            conditions.extend(["e.ENTITY_TYPE='SKILL'", "e.STATUS='ACTIVE'", "sm.SKILL_STATUS='ACTIVE'"])
            sql = "SELECT e.ENTITY_ID FROM ENTITIES e JOIN SKILL_META sm ON sm.ENTITY_ID=e.ENTITY_ID"
            if "ALL" not in access.get("scopes", []):
                conditions.append("(e.OWNED_BY_AGENT=:actor OR e.VISIBILITY='PUBLIC')")
                params["actor"] = actor
        else:
            key, field = "t.TOOL_ID", "t.TOOL_NAME"
            conditions.extend(["t.STATUS='ACTIVE'", "t.MCP_EXPOSED='Y'"])
            sql = "SELECT t.TOOL_ID FROM CX_MCP_EXPOSED_TOOLS t"
        if after:
            conditions.append(key + ">:after")
            if connection.DATABASE_DIALECT in {"pg", "postgresql"} and family == "SKILL":
                try:
                    params["after"] = int(after)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Skill cursor is invalid") from exc
            elif connection.DATABASE_DIALECT in {"pg", "postgresql"} and family == "TOOL":
                try:
                    params["after"] = int(after)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Tool cursor is invalid") from exc
            else:
                params["after"] = after
        if query:
            conditions.append("LOWER(" + field + ") LIKE :query ESCAPE '!'")
            params["query"] = "%" + query.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        identifiers = [row(item) for item in tx.query(sql + " WHERE " + " AND ".join(conditions) + " ORDER BY " + key + identity_api._limit_clause("page_limit"), params)]
        items = []
        for candidate in identifiers[:int(limit)]:
            identifier = candidate["entity_id" if family == "SKILL" else "tool_id"]
            value = skill_api.get_skill(identifier) if family == "SKILL" else tool_registry.get_tool(identifier)
            if not value or family == "SKILL" and not _skill_visible(actor, value, access):
                continue
            metadata, _ = _metadata(family, value)
            items.append(metadata)
        _authority(tx, actor, domain, family)
        return {"items": items, "next_cursor": str(identifiers[int(limit) - 1]["entity_id" if family == "SKILL" else "tool_id"]) if len(identifiers) > int(limit) else None,
                "body_loaded_for_client": False, "discovery_grants_execution": False}
    return connection.execute_transaction_callback(perform)


def load(actor, domain, family, entity_id, version, content_digest):
    if family not in {"SKILL", "TOOL"}:
        raise ValueError("Invalid directory family")
    def perform(tx):
        access = _authority(tx, actor, domain, family)
        value = skill_api.get_skill(entity_id) if family == "SKILL" else tool_registry.get_tool(entity_id)
        if (not value or family == "SKILL" and (value.get("skill_status") != "ACTIVE" or not _skill_visible(actor, value, access)) or
                family == "TOOL" and (value.get("status") != "ACTIVE" or value.get("mcp_exposed") != "Y")):
            raise PermissionError("Directory entry was withdrawn")
        metadata, content = _metadata(family, value)
        if metadata["version"] != version or metadata["content_digest"] != content_digest:
            raise ValueError("Directory entry version or content changed")
        _authority(tx, actor, domain, family)
        return {**metadata, "content": content, "execution_authorized": False}
    return connection.execute_transaction_callback(perform)
