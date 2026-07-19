"""AI Agent Infra v4.0.0 - MCP Server

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
    tool_registry, graph_api, loop_api, agent_api,
)
from lib.config import get_config
from lib.connection import execute_query

server = Server("ai-agent-infra")

DYNAMIC_TOOL_PREFIX = "DYN_"


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

    tools.extend(_load_dynamic_tools())

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
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
            )
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        elif name == "memory_create":
            mid = memory_api.create_memory(
                title=arguments.get("title", ""),
                content=arguments.get("content", ""),
                category=arguments.get("category", "general"),
                importance=arguments.get("importance", 5),
                source_agent=arguments.get("source_agent", arguments.get("owned_by_agent", "")),
                owned_by_agent=arguments.get("owned_by_agent", ""),
                visibility=arguments.get("visibility", "PRIVATE"),
            )
            return [TextContent(type="text", text=json.dumps({"memory_id": mid, "success": bool(mid)}))]

        elif name == "memory_search":
            results = memory_api.search_memories(
                keyword=arguments.get("keyword", ""),
                owned_by_agent=arguments.get("owned_by_agent"),
                limit=arguments.get("limit", 20),
            )
            return [TextContent(type="text", text=json.dumps(results, default=str, ensure_ascii=False))]

        elif name == "knowledge_create":
            kid = knowledge_api.create_knowledge(
                title=arguments.get("title", ""),
                content=arguments.get("content", ""),
                domain=arguments.get("domain"),
                topic=arguments.get("topic"),
                importance=arguments.get("importance", 5),
                owned_by_agent=arguments.get("owned_by_agent", ""),
                visibility=arguments.get("visibility", "SHARED"),
            )
            return [TextContent(type="text", text=json.dumps({"knowledge_id": kid, "success": bool(kid)}))]

        elif name == "knowledge_search":
            results = knowledge_api.search_knowledge(
                keyword=arguments.get("keyword", ""),
                domain=arguments.get("domain"),
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
            neighbors = graph_api.get_neighbors(arguments.get("entity_id", ""))
            return [TextContent(type="text", text=json.dumps(neighbors, default=str, ensure_ascii=False))]

        elif name == "loop_status":
            run = loop_api.get_run(arguments.get("run_id", ""))
            return [TextContent(type="text", text=json.dumps(run, default=str, ensure_ascii=False))]

        elif name == "agent_list":
            agents = agent_api.list_agents()
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
                "trusted": graph_api.get_trusted_agents(arguments.get("agent_id", ""), arguments.get("group_id", "")),
                "recommendations": graph_api.recommend_collaborators(arguments.get("agent_id", ""), arguments.get("group_id", "")),
            }
            return [TextContent(type="text", text=json.dumps(result, default=str, ensure_ascii=False))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        logger.exception("Tool call error: %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
