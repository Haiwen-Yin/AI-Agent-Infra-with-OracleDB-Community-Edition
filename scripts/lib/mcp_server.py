"""AI Agent Infra v4.4.12 - MCP Server

Exposes the system's tools, memory, knowledge, and search capabilities
as an MCP (Model Context Protocol) server. Supports both stdio and SSE transport.

Usage:
    python mcp_server_main.py --transport stdio
    python mcp_server_main.py --transport sse --port 9000
"""

import json
import logging
import sys
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if os.path.join(_project_root, "lib") not in sys.path:
    sys.path.insert(0, os.path.join(_project_root, "lib"))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool, TextContent, ImageContent, EmbeddedResource,
    LoggingLevel,
)

from lib import (
    search_api, memory_api, knowledge_api,
    tool_registry, graph_api, loop_api, agent_api, skill_acquire_api,
    memory_lifecycle, compliance_api,
)
from lib.config import get_config
from lib.connection import execute_query

server = Server("ai-agent-infra")

DYNAMIC_TOOL_PREFIX = "DYN_"


def _owned_memory_version(version_id: str, agent_id: str) -> None:
    """Require direct ownership before an MCP Agent can read or mutate Memory."""
    row = execute_query(
        "SELECT OWNER_AGENT_ID FROM CX_MEMORY_VERSIONS WHERE VERSION_ID = :version_id",
        {"version_id": version_id},
    )
    owner = str((row[0] if row else {}).get("owner_agent_id") or "")
    if owner != agent_id:
        raise PermissionError("Memory version is outside the authenticated Agent scope")


def _authenticated_mcp_agent() -> str:
    """Resolve MCP identity from the transport environment, never arguments."""
    from lib import agent_registration
    from lib.connection import set_agent_context

    agent_id = (os.environ.get("AI_AGENT_ID") or os.environ.get("MCP_AGENT_ID") or "").strip()
    token = os.environ.get("AI_AGENT_TOKEN") or os.environ.get("MCP_AGENT_TOKEN") or ""
    if not agent_id or not token or not agent_registration.authenticate_agent(agent_id, token):
        raise PermissionError("registered Agent authentication required")
    set_agent_context(agent_id)
    return agent_id


def _get_exposed_tools() -> List[str]:
    cfg = get_config()
    return list(cfg.mcp.exposed_tools)


def _load_dynamic_tools() -> List[Tool]:
    tools: List[Tool] = []
    try:
        rows = execute_query(
            """SELECT TOOL_ID, TOOL_NAME, DESCRIPTION, INPUT_SCHEMA
               FROM TOOL_REGISTRY
               WHERE MCP_EXPOSED = 'Y' AND STATUS = 'ACTIVE'""",
            {},
        )
    except Exception as e:
        logger.warning(
            "Dynamic tool loading skipped (TOOL_REGISTRY.MCP_EXPOSED unavailable): %s", e
        )
        return tools

    for row in rows:
        try:
            tool_id = row[0] if not isinstance(row, dict) else row.get("tool_id")
            tool_name = row[1] if not isinstance(row, dict) else row.get("tool_name")
            description = row[2] if not isinstance(row, dict) else row.get("description")
            input_schema = row[3] if not isinstance(row, dict) else row.get("input_schema")

            if not tool_id or not tool_name:
                continue

            if isinstance(input_schema, str):
                try:
                    input_schema = json.loads(input_schema)
                except (json.JSONDecodeError, TypeError):
                    input_schema = {"type": "object", "properties": {}}
            elif input_schema is None:
                input_schema = {"type": "object", "properties": {}}

            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}}

            if not description:
                description = f"Dynamic tool {tool_name} (registry id: {tool_id})"

            tools.append(Tool(
                name=f"{DYNAMIC_TOOL_PREFIX}{tool_id}",
                description=description,
                inputSchema=input_schema,
            ))
        except Exception as e:
            logger.warning("Skipping dynamic tool row %s: %s", row, e)
            continue

    logger.info("Loaded %d dynamic tools from TOOL_REGISTRY (MCP_EXPOSED='Y')", len(tools))
    return tools


@server.list_tools()
async def list_tools() -> List[Tool]:
    _authenticated_mcp_agent()
    exposed = _get_exposed_tools()
    tools = []

    if "search" in exposed:
        tools.append(Tool(
            name="search",
            description="Unified search across memory, knowledge, and graph. Supports 10 strategies: vector, fulltext, keyword, graph, hybrid, unified, unified_sql, relational, multi_type, auto.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Search query text"},
                    "strategy": {"type": "string", "default": "auto", "enum": [
                        "auto", "vector", "fulltext", "keyword", "graph",
                        "hybrid", "unified", "unified_sql", "relational", "multi_type"
                    ]},
                    "top_k": {"type": "integer", "default": 10},
                    "entity_type": {"type": "string"},
                    "domain": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["text"],
            },
        ))

    if "memory_create" in exposed:
        tools.append(Tool(
            name="memory_create",
            description="Create a new memory entry for an agent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "category": {"type": "string", "default": "general"},
                    "importance": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                    "source_agent": {"type": "string"},
                    "owned_by_agent": {"type": "string"},
                    "visibility": {"type": "string", "default": "PRIVATE"},
                },
                "required": ["title", "content", "owned_by_agent"],
            },
        ))

    if "memory_search" in exposed:
        tools.append(Tool(
            name="memory_search",
            description="Search agent memories by keyword.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "owned_by_agent": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["keyword"],
            },
        ))

    if "memory_lifecycle_create" in exposed:
        tools.append(Tool(
            name="memory_lifecycle_create",
            description="Create an immutable version-one Memory Family owned by the authenticated Agent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "memory_type": {"type": "string", "default": "EPISODIC"},
                    "memory_scope": {"type": "string", "default": "AGENT_MEMORY"},
                    "classification": {"type": "string", "default": "INTERNAL"},
                    "reason": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["title", "body"],
            },
        ))

    if "memory_lifecycle_chain" in exposed:
        tools.append(Tool(
            name="memory_lifecycle_chain",
            description="Read a bounded relation chain for an authenticated Agent-owned Memory Family.",
            inputSchema={
                "type": "object",
                "properties": {
                    "family_id": {"type": "string"},
                    "hops": {"type": "integer", "default": 2, "minimum": 1, "maximum": 6},
                    "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 250},
                },
                "required": ["family_id"],
            },
        ))

    if "memory_lifecycle_feedback" in exposed:
        tools.append(Tool(
            name="memory_lifecycle_feedback",
            description="Record attributed feedback for an authenticated Agent-owned Memory Version.",
            inputSchema={
                "type": "object",
                "properties": {
                    "version_id": {"type": "string"},
                    "outcome": {"type": "string", "enum": ["HELPFUL", "UNHELPFUL", "STALE"]},
                    "purpose": {"type": "string", "default": "RUNTIME_CONTEXT"},
                    "run_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["version_id", "outcome"],
            },
        ))

    if "memory_lifecycle_candidate" in exposed:
        tools.append(Tool(
            name="memory_lifecycle_candidate",
            description="Submit a candidate for review; this never changes the current Memory Version directly.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_version_id": {"type": "string"},
                    "candidate_type": {"type": "string", "enum": ["REPLACE", "MERGE", "CONFLICT", "SCOPE_CHANGE"]},
                    "proposed": {"type": "object"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["source_version_id", "candidate_type", "proposed", "reason"],
            },
        ))

    if "knowledge_create" in exposed:
        tools.append(Tool(
            name="knowledge_create",
            description="Create a new knowledge entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "domain": {"type": "string"},
                    "topic": {"type": "string"},
                    "importance": {"type": "integer", "default": 5},
                    "owned_by_agent": {"type": "string"},
                    "visibility": {"type": "string", "default": "SHARED"},
                    "sharing_scope": {"type": "string", "enum": ["PUBLIC_COMPANY", "ORGANIZATION_SUBTREE", "ORGANIZATION_LEVEL", "PRINCIPAL_PRIVATE"], "default": "ORGANIZATION_SUBTREE"},
                    "organization_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["title", "content", "owned_by_agent"],
            },
        ))

    if "knowledge_search" in exposed:
        tools.append(Tool(
            name="knowledge_search",
            description="Search knowledge base by keyword.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "domain": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["keyword"],
            },
        ))

    if "tool_list" in exposed:
        tools.append(Tool(
            name="tool_list",
            description="List all registered tools in the tool registry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "tool_type": {"type": "string"},
                },
            },
        ))

    if "tool_invoke" in exposed:
        tools.append(Tool(
            name="tool_invoke",
            description="Invoke a registered tool by its tool_id with input parameters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_id": {"type": "string"},
                    "input_params": {"type": "object"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["tool_id"],
            },
        ))

    if "graph_neighbors" in exposed:
        tools.append(Tool(
            name="graph_neighbors",
            description="Get neighbor nodes in the knowledge graph for a given entity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "depth": {"type": "integer", "default": 1},
                },
                "required": ["entity_id"],
            },
        ))

    if "loop_status" in exposed:
        tools.append(Tool(
            name="loop_status",
            description="Get the status of a loop run.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                },
                "required": ["run_id"],
            },
        ))

    if "agent_list" in exposed:
        tools.append(Tool(
            name="agent_list",
            description="List all registered agents.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ))

    if "skill_discover" in exposed:
        tools.append(Tool(
            name="skill_discover",
            description="Discover Skills visible to the authenticated Agent.",
            inputSchema={"type": "object", "properties": {
                "keyword": {"type": "string"}, "runtime": {"type": "string"},
                "skill_type": {"type": "string"}, "skill_format": {"type": "string"},
            }},
        ))

    if "skill_describe" in exposed:
        tools.append(Tool(
            name="skill_describe",
            description="Describe a Skill and return its complete SKILL.md content.",
            inputSchema={"type": "object", "properties": {
                "skill_id": {"type": "string"},
            }, "required": ["skill_id"]},
        ))

    if "skill_acquire" in exposed:
        tools.append(Tool(
            name="skill_acquire",
            description="Acquire Skill metadata, complete SKILL.md, and package integrity metadata.",
            inputSchema={"type": "object", "properties": {
                "skill_id": {"type": "string"},
            }, "required": ["skill_id"]},
        ))

    if "skill_status" in exposed:
        tools.append(Tool(
            name="skill_status",
            description="Inspect Skill availability and installation status.",
            inputSchema={"type": "object", "properties": {
                "skill_id": {"type": "string"},
            }, "required": ["skill_id"]},
        ))

    if "graph_causal" in exposed:
        tools.append(Tool(
            name="graph_causal",
            description="Trace causal relationships, contradictions, and provenance for an entity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "depth": {"type": "integer", "default": 3},
                },
                "required": ["entity_id"],
            },
        ))

    if "graph_lineage" in exposed:
        tools.append(Tool(
            name="graph_lineage",
            description="Trace data lineage: derivation chain + access history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                },
                "required": ["entity_id"],
            },
        ))

    if "graph_collaboration" in exposed:
        tools.append(Tool(
            name="graph_collaboration",
            description="Get trusted agents and collaboration recommendations within a group.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "group_id": {"type": "string"},
                },
                "required": ["agent_id", "group_id"],
            },
        ))

    # Compliance tools deliberately use the same database-authoritative
    # service as REST/Gateway.  They are visible to a registered Agent only
    # for its own posture and bounded, untrusted boundary evidence.
    tools.extend([
        Tool(name="compliance_posture", description="Inspect the authenticated Agent's current compliance posture.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="compliance_profile", description="Inspect the authenticated Agent's assigned governed Profile identifier.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="compliance_evidence", description="Submit bounded advisory runtime evidence for the authenticated Agent.", inputSchema={"type": "object", "properties": {"evidence_type": {"type": "string"}, "payload": {"type": "object"}, "nonce": {"type": "string"}}, "required": ["evidence_type", "payload"]}),
    ])

    tools.extend(_load_dynamic_tools())

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        authenticated_agent = _authenticated_mcp_agent()
        if name.startswith(DYNAMIC_TOOL_PREFIX):
            tool_id = name[len(DYNAMIC_TOOL_PREFIX):]
            result = tool_registry.invoke_tool(
                tool_id=tool_id,
                input_params=arguments,
                timeout=arguments.get("timeout", 30) if isinstance(arguments, dict) else 30,
            )
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        if name == "search":
            result = search_api.search(
                text=arguments.get("text", ""),
                strategy=arguments.get("strategy", "auto"),
                top_k=arguments.get("top_k", 10),
                entity_type=arguments.get("entity_type"),
                domain=arguments.get("domain"),
                category=arguments.get("category"),
                principal_id=authenticated_agent,
            )
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]
        elif name == "compliance_posture":
            result = compliance_api.runtime_posture(authenticated_agent)
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]
        elif name == "compliance_profile":
            posture = compliance_api.runtime_posture(authenticated_agent)
            result = {"agent_id": authenticated_agent, "profile_version_id": posture.get("profile_version_id"),
                      "evidence_strength": posture.get("evidence_strength"), "activation_id": posture.get("activation_id")}
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]
        elif name == "compliance_evidence":
            result = compliance_api.submit_mcp_evidence(authenticated_agent, arguments.get("evidence_type", ""), arguments.get("payload", {}), nonce=arguments.get("nonce", ""))
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]
        elif name == "skill_discover":
            result = skill_acquire_api.discover_skills(
                skill_type=arguments.get("skill_type"), runtime=arguments.get("runtime"),
                skill_format=arguments.get("skill_format"), keyword=arguments.get("keyword"),
            )
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]
        elif name == "skill_describe":
            result = skill_acquire_api.acquire_skill_text(arguments["skill_id"])
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]
        elif name == "skill_acquire":
            result = skill_acquire_api.acquire_skill_full(arguments["skill_id"])
            if result:
                result.pop("resource_zip", None)
                result["installation"] = skill_acquire_api.materialize_skill(arguments["skill_id"], agent_id=authenticated_agent)
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]
        elif name == "skill_status":
            skill = skill_acquire_api.acquire_skill_text(arguments["skill_id"])
            result = {"skill_id": arguments["skill_id"], "available": skill is not None,
                      "status": "AVAILABLE" if skill else "NOT_FOUND"}
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "memory_create":
            mid = memory_api.create_memory(
                title=arguments.get("title", ""),
                content=arguments.get("content", ""),
                category=arguments.get("category", "general"),
                importance=arguments.get("importance", 5),
                source_agent=authenticated_agent,
                owned_by_agent=authenticated_agent,
                visibility=arguments.get("visibility", "PRIVATE"),
            )
            return [TextContent(type="text", text=json.dumps({"memory_id": mid, "success": bool(mid)}))]

        elif name == "memory_search":
            results = memory_api.search_memories(
                keyword=arguments.get("keyword", ""),
                owned_by_agent=authenticated_agent,
                limit=arguments.get("limit", 20),
            )
            return [TextContent(type="text", text=json.dumps(results, default=str, ensure_ascii=False))]

        elif name == "memory_lifecycle_create":
            memory_scope = str(arguments.get("memory_scope", "AGENT_MEMORY")).upper()
            if memory_scope not in {"AGENT_MEMORY", "RUNTIME_CONTEXT"}:
                raise PermissionError("MCP Agent memory creation is limited to Agent-owned scopes")
            result = memory_lifecycle.create_family({
                "title": arguments.get("title", ""),
                "body": arguments.get("body", ""),
                "memory_type": arguments.get("memory_type", "EPISODIC"),
                "memory_scope": memory_scope,
                "classification": arguments.get("classification", "INTERNAL"),
                "owner_agent_id": authenticated_agent,
                "owner_principal_id": f"AGENT:{authenticated_agent}",
                "reason": arguments.get("reason", "MCP Agent memory creation"),
            }, actor=f"AGENT:{authenticated_agent}", idempotency_key=arguments.get("idempotency_key"))
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "memory_lifecycle_chain":
            family = memory_lifecycle.get_family(arguments["family_id"])
            current = (family or {}).get("current")
            if not current:
                raise ValueError("Memory Family is unavailable")
            _owned_memory_version(str(current["version_id"]), authenticated_agent)
            result = memory_lifecycle.chain(
                str(current["version_id"]), hops=arguments.get("hops", 2), limit=arguments.get("limit", 100),
            )
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "memory_lifecycle_feedback":
            version_id = str(arguments["version_id"])
            _owned_memory_version(version_id, authenticated_agent)
            event_id = memory_lifecycle.record_usage(
                version_id, "AGENT_FEEDBACK", agent_id=authenticated_agent,
                run_id=arguments.get("run_id"), purpose=arguments.get("purpose", "RUNTIME_CONTEXT"),
                outcome=arguments["outcome"], idempotency_key=arguments.get("idempotency_key"),
            )
            return [TextContent(type="text", text=json.dumps({"usage_event_id": event_id}, ensure_ascii=False))]

        elif name == "memory_lifecycle_candidate":
            source_version_id = str(arguments["source_version_id"])
            _owned_memory_version(source_version_id, authenticated_agent)
            result = memory_lifecycle.create_candidate(
                str(arguments["candidate_type"]), source_version_id, arguments["proposed"],
                actor=f"AGENT:{authenticated_agent}", confidence=arguments.get("confidence"),
                reason=str(arguments["reason"]), idempotency_key=arguments.get("idempotency_key"),
            )
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "knowledge_create":
            kid = knowledge_api.create_knowledge(
                title=arguments.get("title", ""),
                content=arguments.get("content", ""),
                domain=arguments.get("domain"),
                topic=arguments.get("topic"),
                importance=arguments.get("importance", 5),
                owned_by_agent=authenticated_agent,
                visibility=arguments.get("visibility", "SHARED"),
                sharing_scope=arguments.get("sharing_scope", "ORGANIZATION_SUBTREE"),
                organization_id=arguments.get("organization_id"),
                creation_reason=arguments.get("reason", "Agent knowledge creation"),
            )
            return [TextContent(type="text", text=json.dumps({"knowledge_id": kid, "success": bool(kid)}))]

        elif name == "knowledge_search":
            results = knowledge_api.search_knowledge(
                keyword=arguments.get("keyword", ""),
                domain=arguments.get("domain"),
                principal_id=authenticated_agent,
            )
            return [TextContent(type="text", text=json.dumps(results, default=str, ensure_ascii=False))]

        elif name == "tool_list":
            tools = tool_registry.list_tools(
                namespace=arguments.get("namespace"),
                tool_type=arguments.get("tool_type"),
            )
            return [TextContent(type="text", text=json.dumps(tools, default=str, ensure_ascii=False))]

        elif name == "tool_invoke":
            result = tool_registry.invoke_tool(
                tool_id=arguments.get("tool_id", ""),
                input_params=arguments.get("input_params"),
                timeout=arguments.get("timeout", 30),
            )
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "graph_neighbors":
            neighbors = graph_api.get_neighbors(
                arguments.get("entity_id", ""), principal_id=authenticated_agent,
            )
            return [TextContent(type="text", text=json.dumps(neighbors, default=str, ensure_ascii=False))]

        elif name == "loop_status":
            run = loop_api.get_run(arguments.get("run_id", ""))
            return [TextContent(type="text", text=json.dumps(run, default=str, ensure_ascii=False))]

        elif name == "agent_list":
            from lib import agent_registration
            agents = agent_registration.list_registrations()
            return [TextContent(type="text", text=json.dumps(agents, default=str, ensure_ascii=False))]

        elif name == "graph_causal":
            result = {
                "causes": graph_api.find_causes(arguments.get("entity_id", ""), arguments.get("depth", 3)),
                "contradictions": graph_api.find_contradictions(arguments.get("entity_id", "")),
                "provenance": graph_api.trace_provenance(arguments.get("entity_id", "")),
            }
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "graph_lineage":
            result = graph_api.trace_data_lineage(arguments.get("entity_id", ""))
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "graph_collaboration":
            result = {
                "trusted": graph_api.get_trusted_agents(authenticated_agent, arguments.get("group_id", "")),
                "recommendations": graph_api.recommend_collaborators(authenticated_agent, arguments.get("group_id", "")),
            }
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        logger.exception("Tool call error: %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
