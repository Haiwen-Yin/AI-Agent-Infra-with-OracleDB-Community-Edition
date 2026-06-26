# Release Notes — v3.7.4

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-26

License: Apache License 2.0

Official Website: https://db4agent.top

---

## Overview

v3.7.4 introduces 6 major expansion directions: Agent Communication Protocol, Multi-Agent Orchestration, Event-Driven Architecture, Advanced Memory Management, Observability, and Tool Ecosystem. 9 new database tables, 3 new PL/SQL packages, 3 new scheduler jobs, and 6 new Python modules.

---

## New Features

- **Agent Communication Protocol** — COLLAB_MESSAGES table + message_api.py (15 functions) for inter-agent messaging, threaded replies, broadcast, priority levels
- **Multi-Agent Orchestration** — orchestrator.py DAG execution engine with topological sorting, parallel execution groups, fan-out/fan-in (CONSENSUS/BEST_OF_N/CONCATENATE/FIRST), retry policies, pipeline composition
- **Event-Driven Architecture** — EVENT_LOG + EVENT_SUBSCRIPTIONS for publish/subscribe, LOOP_HOOKS execution engine (WEBHOOK/SCRIPT/NOTIFICATION/MCP_CALL), agent capability discovery
- **Advanced Memory Management** — branch memory consolidation, episodic-to-semantic promotion, knowledge merging (OVERWRITE/UNION/WEIGHTED), conflict detection
- **Observability** — Distributed tracing (TRACE_ID across sessions/plans/loops/tool_calls), agent health dashboard, performance metrics, drift detection, alert rule engine
- **Tool Ecosystem** — OpenAPI spec auto-import tool definitions, TOOL_REGISTRY with versioning, tool DAG chains (TOOL_CHAINS + TOOL_CHAIN_STEPS)

---

## Database Changes

- **New tables (9)**: COLLAB_MESSAGES, STEP_RETRY_POLICY, STEP_EXECUTION_PLAN, EVENT_LOG, EVENT_SUBSCRIPTIONS, AGENT_CAPABILITY_INDEX, TOOL_REGISTRY, TOOL_CHAINS, TOOL_CHAIN_STEPS
- **Total tables**: 44
- **TRACE_ID columns**: Added to AGENT_SESSION, TASK_PLANS, LOOP_RUNS, TASK_TOOL_CALLS, ENTITY_ACCESS_LOG, WORKSPACE_CONTEXT

---

## API Changes

### New Python Modules
- `scripts/lib/message_api.py` — 15 functions for Agent Communication Protocol
- `scripts/lib/orchestrator.py` — 8 functions for DAG orchestration
- `scripts/lib/event_bus.py` — 12 functions for event pub/sub, hooks, capability discovery
- `scripts/lib/trace_api.py` — 6 functions for distributed tracing
- `scripts/lib/monitor_api.py` — 6 functions for health monitoring
- `scripts/lib/tool_registry.py` — 14 functions for tool management

### New PL/SQL Packages (3)
- COLLAB_MESSAGE_MANAGER — Server-side message CRUD and threading
- TRACE_MANAGER — Trace tree queries and span counting
- MONITOR_MANAGER — Agent stall detection, plan counts, token usage trends

### New Scheduler Jobs (3)
- DAG_RESOLVER_JOB — Every 5 min, resolve pending DAG execution plans
- HOOK_EXECUTOR_JOB — Every 1 min, process queued hook executions
- ALERT_EVALUATOR_JOB — Every 5 min, evaluate alert rules

### New Monitor Page
- `/monitor` — System monitoring dashboard with agent health, performance metrics, stalled detection

---

## Upgrade Notes

### Fresh Deployment
1. Deploy `1_schema.sql → 2_api.sql → 3_jobs.sql → 4_harness_templates.sql, Oracle only: 4_grants.sql → 6_deep_sec_policy.sql`
2. Edit `config.json` with database and embedding configuration
3. Start the web portal: `nohup python3 scripts/visualization/server.py > server.log 2>&1 &`

### Upgrading from v3.7.3
- Replace all Python lib/*.py and visualization/server.py files
- Deploy `1_schema.sql` (ALTER TABLE + new CREATE TABLE)
- Deploy `2_api.sql` (new PL/SQL packages)
- No data migration required
