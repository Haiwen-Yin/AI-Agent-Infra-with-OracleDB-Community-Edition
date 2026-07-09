# Release Notes - v3.10.0 (2026-07-09) - Community Edition

## Overview

**v3.10.0** is the Universal Property Graph release. This version extends the graph model from entity-level adjacency to 8 functional domains, adding 30+ graph functions and 23 new edge types. The property graph now covers knowledge causality, agent collaboration, task orchestration, skill dependencies, approval propagation, data flow, memory evolution, and loop iteration relationships.

## New Features

### Universal Property Graph (30+ Functions, 23 Edge Types)

**1. Knowledge Causal Graph**: CAUSES, CONTRADICTS, SUPERSEDES, DERIVED_FROM edges. Functions: add_causal_edge, find_causes, find_contradictions, trace_provenance, supersede_knowledge.

**2. Agent Collaboration Graph**: TRUSTS, DELEGATED_TO, COMPLEMENTS_SKILL, COMMUNICATED_WITH edges. Group-scoped dynamic trust with configurable delta values. Functions: init_group_trust, get_trusted_agents, update_trust, recommend_collaborators, record_delegation, find_complementary_agents.

**3. Task Orchestration Graph**: FEEDS_INTO, PRODUCED_ARTIFACT, CONSUMED_ARTIFACT, REQUIRES_OUTPUT_OF edges. Functions: record_task_dependency, get_task_lineage, find_affected_steps, get_artifact_chain.

**4. Skill Dependency Graph**: REQUIRES, ENHANCES edges. Functions: add_skill_dependency, get_required_skills, find_skill_gaps.

**5. Approval Propagation Graph**: BLOCKS, DEPENDS_ON edges with cascade reject. Functions: add_approval_block, cascade_reject, find_approval_bottlenecks.

**6. Data Flow**: DERIVED_FROM_DATA graph edge + existing audit table queries. Functions: trace_data_lineage, find_data_paths.

**7. Memory Evolution Graph**: PROMOTED_TO, MERGED_INTO, SUPERSEDED_BY edges. Functions: record_promotion, record_merge, trace_memory_origin.

**8. Loop Iteration Graph**: BUILDS_ON, INFORMS, CORRECTS edges. Functions: record_iteration_link, get_iteration_graph, find_key_iterations.

### Dynamic Trust Configuration

Trust adjustment rates are configurable via SYSTEM_CONFIG:
- trust_success_delta (default 0.1)
- trust_failure_delta (default 0.15)
- trust_min_threshold (default 0.3)
- trust_max_value (default 1.0)
- trust_initial_coordinator (default 0.5)
- trust_initial_member (default 0.3)

### New API Endpoints

- GET /api/graph/causal - Trace causal relationships and provenance
- GET /api/graph/collaboration - Get trusted agents and recommendations
- GET /api/graph/lineage - Trace data lineage

### New MCP Tools

- graph_causal - Trace causal relationships for an entity
- graph_lineage - Trace data lineage
- graph_collaboration - Get trusted agents within a group

## Database Changes

- New index: IDX_EDGES_EDGE_TYPE on ENTITY_EDGES(EDGE_TYPE) LOCAL
- New SYSTEM_CONFIG entries: 6 trust configuration values
- No new tables (audit events use existing ENTITY_ACCESS_AUDIT / CONTEXT_AUDIT_LOG)

## Bug Fixes

### PG Editions
- Fixed audit_api.purge_audit_logs: access_time -> accessed_at column name
- Added missing AGE create_graph call in deployment scripts

### All Editions
- Fixed edition label in memory_api.py and knowledge_api.py (Oracle ENT said Community Edition)
- Fixed graph_api.py version string (was v3.5.0)

## Upgrade Notes

1. Deploy 1_schema.sql changes (index + config entries)
2. For PG: redeploy 2_api.sql to pick up purge_audit_logs fix
3. Replace graph_api.py, collab_api.py, memory_api.py with updated versions
4. No data migration required
