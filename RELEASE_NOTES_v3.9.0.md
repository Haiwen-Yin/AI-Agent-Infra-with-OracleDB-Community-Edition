# Release Notes — v3.9.0 (2026-07-05) — Community Edition

## Overview

**v3.9.0** is the AI Agent ecosystem connectivity release. This version adds MCP (Model Context Protocol) server support, SSE streaming output, Human-in-the-Loop approval workflows, Agent Protocol compatibility, and multi-model routing — connecting the system's rich capabilities to external AI clients and frameworks.

## New Features

### 1. MCP Server (Model Context Protocol)

Exposes the system's tools, memory, knowledge, and search as a standard MCP server. External AI clients (Claude Desktop, Cursor, VS Code Copilot) can directly connect and use the system's capabilities.

- **10 MCP Tools**: search, memory_create, memory_search, knowledge_create, knowledge_search, tool_list, tool_invoke, graph_neighbors, loop_status, agent_list
- **Dual transport**: stdio (for local clients) and SSE (for remote connections)
- **Configurable**: select which tools to expose via config.json

### 2. SSE Streaming Output

Web Portal chat now supports token-by-token streaming output via Server-Sent Events (SSE). Agent responses appear in real-time instead of waiting for the complete reply.

-  response
-  per-token format
- Falls back to non-streaming mode if LLM not configured

### 3. Human-in-the-Loop Approval

Three-level approval workflow for enterprise governance:

- **Step-level**: Orchestrator DAG steps can require approval before execution (PAUSED state)
- **Loop-level**: Loop runs can require approval before starting
- **Tool-level**: Tool invocations can require approval before HTTP call
- Unified approval queue with API and web UI

### 4. Agent Protocol Compatibility

Standard Agent Protocol API endpoints for interoperability with benchmark tools:

-  — create task
-  — execute step
-  — list tasks
-  — list steps

### 5. Multi-Model Routing

Configurable model routing based on task complexity:

- **Simple model**: for low-complexity tasks (summaries, classification)
- **Standard model**: default for most tasks
- **Complex model**: for high-complexity tasks (code generation, reasoning)
- Routing rules configurable via config.json

## Database Changes

- `STEP_EXECUTION_PLAN`: Added REQUIRES_APPROVAL, APPROVED_BY, APPROVED_AT columns
- `LOOP_META`: Added REQUIRE_APPROVAL column
- `TOOL_REGISTRY`: Added REQUIRES_APPROVAL column
- `CK_SEP_STATUS` constraint: Added 'PAUSED' value
- New table: `APPROVAL_REQUESTS` (unified approval queue)

## New Files

- `scripts/lib/mcp_server.py` — MCP Server implementation
- `scripts/mcp_server_main.py` — MCP Server entry point
- `scripts/lib/approval_api.py` — Unified approval management API
- `scripts/visualization/templates/approvals.html` — Approval queue page

## Upgrade Notes

1. Deploy  to apply schema changes (3 new columns + 1 new table)
2. Install MCP SDK:  (requires Python 3.10+)
3. Add , ,  sections to 
4. No data migration required
