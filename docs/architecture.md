# Architecture - Oracle Memory System v2.1.0

## Unified Entity Model

v2.1 extends the unified model with composite primary keys, partitioning, and denormalized columns.

### ENTITIES

Single table with `ENTITY_TYPE` discriminator, composite PK `(ENTITY_ID, ENTITY_TYPE)`:

- **MEMORY**: Short-term agent memories. Fields: title, content, summary, category, importance, status, visibility, source_agent
- **KNOWLEDGE**: Long-term validated knowledge. Extended by KNOWLEDGE_META for domain, topic, difficulty, spaced review
- **TASK_OUTPUT**: Task execution results
- **EXPERIENCE**: Learned patterns and heuristics
- **HARNESS_TEMPLATE**: Reusable agent execution blueprints. Extended by HARNESS_META for input_schema, output_schema, execution_mode
- **OTHER**: Catch-all for future entity types

**v2.1 column changes from v2.0**:

| v2.0 Column | v2.1 Column | Notes |
|-------------|-------------|-------|
| NAME | TITLE | Renamed |
| PRIORITY | IMPORTANCE | Renamed, range 1-10 |
| TAGS (JSON) | ENTITY_TAGS + TAGS tables | Normalized into separate tables |
| METADATA (JSON) | *(removed)* | Only on ENTITY_EDGES now |
| ACCESSIBLE_TO (JSON) | *(removed)* | Visibility simplified to PRIVATE/SHARED/PUBLIC |
| DESCRIPTION | *(removed)* | SUMMARY replaces it on ENTITIES; DESCRIPTION lives on TASK_STEPS |
| *(new)* | SUMMARY | VARCHAR2(2000) entity summary |
| *(new)* | SOURCE_AGENT | VARCHAR2(64) creating agent |
| *(new)* | RETRIEVAL_COUNT | NUMBER(10,0) access counter |
| *(new)* | IMPORTANCE | NUMBER(3,0) 1-10, replaces PRIORITY |

### ENTITY_EDGES

Unified directed edge table with composite PK `(EDGE_ID, SOURCE_ID)`:

- **SOURCE_TYPE**: Denormalized ENTITY_TYPE of the source entity (required for composite FK)
- FK: `(SOURCE_ID, SOURCE_TYPE)` references `ENTITIES(ENTITY_ID, ENTITY_TYPE)`
- Edge types: DEPENDS_ON, RELATED_TO, DERIVED_FROM, CAUSES, ENABLES, PREVENTS, SIMILAR_TO, EVOLVED_FROM, CONTRADICTS, SUPPORTS
- METADATA (JSON) column on edges only

## Composite Primary Keys & Denormalized ENTITY_TYPE

v2.1 uses composite PKs to enable partition-by-reference on child tables. The `ENTITY_TYPE` column is denormalized onto every child table that references ENTITIES:

| Table | PK | FK to ENTITIES | Denormalized Column |
|-------|----|----------------|-------------------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | — | — |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | (SOURCE_ID, SOURCE_TYPE) | SOURCE_TYPE |
| KNOWLEDGE_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_EMBEDDINGS | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| HARNESS_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_TAGS | (ENTITY_ID, ENTITY_TYPE, TAG_ID) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |

TASK_PLANS and TASK_STEPS also use composite PKs:

| Table | PK | UK |
|-------|----|----|
| TASK_PLANS | (PLAN_ID, STATUS) | UK_TASK_PLANS_ID (PLAN_ID) |
| TASK_STEPS | (STEP_ID, PLAN_ID) | UK_TASK_STEPS_ID (STEP_ID) |
| ENTITY_ACCESS_LOG | (LOG_ID) via UK | UK_ACCESS_LOG_ID (LOG_ID) |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | UK_EDGES_ID (EDGE_ID) |
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | UK_ENTITIES_ID (ENTITY_ID) |

Global unique constraints (UK_*) ensure ID uniqueness across partitions when the PK is composite.

## Partitioning Architecture

### ENTITIES — LIST + RANGE (6 partitions × 7 subpartitions = 42 subpartitions)

```
PARTITION BY LIST (ENTITY_TYPE)
  P_MEMORY, P_KNOWLEDGE, P_TASK_OUTPUT, P_EXPERIENCE, P_HARNESS, P_OTHERS

SUBPARTITION BY RANGE (CREATED_AT)
  SP_2026Q1 .. SP_2027Q2, SP_FUTURE
```

Benefits: Queries filtering by ENTITY_TYPE prune to a single partition; time-range queries further prune to subpartitions.

### Reference Partitioned Tables (5 tables)

ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, HARNESS_META, and ENTITY_TAGS inherit their partitioning from the parent ENTITIES table via `PARTITION BY REFERENCE (FK_...)`. This ensures child rows co-locate with their parent entity partition.

### AGENT_SESSION — LIST + RANGE

```
PARTITION BY LIST (IS_ACTIVE): P_ACTIVE('Y'), P_INACTIVE('N')
SUBPARTITION BY RANGE (START_TIME): quarterly subpartitions
```

ROW MOVEMENT enabled — when a session transitions from active to inactive, the row physically moves to the inactive partition.

### TASK_PLANS — LIST + RANGE

```
PARTITION BY LIST (STATUS): P_ACTIVE(PENDING/RUNNING/BLOCKED), P_TERMINAL(SUCCESS/FAILED/CANCELLED)
SUBPARTITION BY RANGE (CREATED_AT): quarterly subpartitions
```

ROW MOVEMENT enabled — plan status changes cause row movement between active/terminal partitions.

TASK_STEPS inherits partitioning via reference to TASK_PLANS.

### ENTITY_ACCESS_LOG — RANGE + HASH

```
PARTITION BY RANGE (ACCESS_TIME): monthly partitions
SUBPARTITION BY HASH (AGENT_ID) SUBPARTITIONS 4
```

Optimized for time-range access log queries with hash-based subpartitioning for concurrent agent access patterns.

### Non-Partitioned Tables

AGENT_REGISTRY, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS, SYSTEM_CONFIG, SYSTEM_USERS.

## Visibility Model

| Level | Behavior |
|-------|----------|
| PRIVATE | Only owner agent can access |
| SHARED | All registered agents can access |
| PUBLIC | Unrestricted access (v2.1 addition, replaces COLLABORATIVE) |

The COLLABORATIVE level and ACCESSIBLE_TO JSON array from v2.0 have been removed. AGENT_COLLABORATION handles cross-agent sharing.

## Property Graph

### ORACLE_MEMORY_GRAPH

Single property graph using composite vertex key `(ENTITY_ID, ENTITY_TYPE)`:

```sql
CREATE PROPERTY GRAPH ORACLE_MEMORY_GRAPH
  VERTEX TABLES (
    ENTITIES KEY (ENTITY_ID, ENTITY_TYPE)
      PROPERTIES (ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
                  OWNED_BY_AGENT, VISIBILITY, IMPORTANCE, CREATED_AT, UPDATED_AT)
  )
  EDGE TABLES (
    ENTITY_EDGES KEY (EDGE_ID, SOURCE_ID)
      SOURCE KEY (SOURCE_ID, SOURCE_TYPE) REFERENCES ENTITIES(ENTITY_ID, ENTITY_TYPE)
      DESTINATION KEY (TARGET_ID) REFERENCES ENTITIES(ENTITY_ID)
      PROPERTIES (EDGE_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, CREATED_AT)
  );
```

### Property Graph API (graph_api.py)

9 Python functions using the `GRAPH_TABLE` SQL operator:

| Function | Description |
|----------|-------------|
| `get_neighbors(entity_id, direction, edge_type, min_strength, limit)` | Get adjacent entities with direction filtering |
| `get_reachable(entity_id, max_hops, edge_type, limit)` | Multi-hop reachability via `{1,max_hops}` pattern |
| `get_shortest_path(source_id, target_id, max_hops)` | Shortest path between two entities (up to 6 hops) |
| `find_similar_entities(entity_id, max_hops, limit)` | Find structurally similar entities via graph proximity |
| `get_entity_context(entity_id, depth)` | Full entity context with neighbors grouped by type/edge |
| `get_graph_stats()` | Graph statistics: vertex/edge counts, degree distribution |
| `get_subgraph(entity_ids, include_intermediate)` | Extract subgraph by entity ID list |
| `find_communities(entity_type, min_connections, limit)` | Find highly-connected entity clusters |
| `graph_search(keyword, entity_type, category, min_importance, limit)` | Graph-aware search via GRAPH_TABLE |

## JSON Duality Views

- **MEMORY_DV**: JSON read/write view for MEMORY-type entities with edges and tags. Uses composite `_id: {entity_id, entity_type}`
- **KNOWLEDGE_DV**: JSON read/write view for KNOWLEDGE-type entities with metadata, edges, and tags

Both views join ENTITY_EDGES on `(SOURCE_ID = ENTITY_ID AND SOURCE_TYPE = ENTITY_TYPE)` and ENTITY_TAGS on `(ENTITY_ID, ENTITY_TYPE)`.

## ID Generation

All IDs are `VARCHAR2(64)`, generated via `RAWTOHEX(SYS_GUID())` producing 32-character hex strings. Prefix conventions: `E_` for edges, `SES_` for sessions, `LOG_` for access logs, `COL_` for collaborations, `PLAN_` for plans, `STEP_` for steps, `SNAP_` for snapshots, `CALL_` for tool calls, `DEP_` for dependencies, `HARNESS_` for templates.

## Design Decisions

1. **Composite PKs** enable partition-by-reference and co-location of parent/child rows
2. **Denormalized ENTITY_TYPE** on child tables required for composite FKs and reference partitioning
3. **ROW MOVEMENT** on AGENT_SESSION, TASK_PLANS, TASK_STEPS allows physical row migration when partition key changes
4. **LIST + RANGE partitioning** on ENTITIES enables type-based pruning + time-based archival
5. **RANGE + HASH** on ENTITY_ACCESS_LOG optimizes for time-range scans with concurrent agent access
6. **Global UK constraints** ensure logical ID uniqueness when PK is composite
7. **Normalized tags** (TAGS + ENTITY_TAGS) replace JSON TAGS column for indexable tag queries
8. **CLOB** for CONTENT fields (large text storage)
9. **VECTOR** for embeddings (compatible with BGE-M3 model)
10. **ON DELETE CASCADE** not used — explicit child-table deletes in Python APIs for safety with partitioned tables
