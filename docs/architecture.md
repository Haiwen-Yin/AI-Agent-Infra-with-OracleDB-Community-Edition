# Architecture - AI Agent Infra v3.9.0 (2026-06-18) - Community Edition

## Unified Entity Model

v2.2 extends the unified model with workspace management, context continuity, and JRD updatable views.

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
Admin Agent (mode=admin)
├── Web Portal (server.py)
├── AIADMIN Connection Pool (full access)
├── Admin Token Generator
├── Admin API Endpoints (/api/admin/agent/*)
└── End User Pool (Deep Sec filtered)
        │  admin_token (secure, out-of-band)
        ▼
Encrypted Credential Distribution
        │
        ▼
Business Agent (mode=agent)
├── Agent Bootstrap CLI
├── End User Connection Pool (Deep Sec filtered)
└── agent_config.json (encrypted at rest)
    ✓ Data Grants always enforced    ✗ No AIADMIN pool    ✗ No Web Portal
```

### Mode Comparison

| Component | standalone | admin | agent |
|-----------|-----------|-------|-------|
| AIADMIN pool | ✓ | ✓ | ✗ |
| End User pool | ✓ | ✓ | ✓ |
| Web Portal | ✓ | ✓ | ✗ |
| agent_config.json | ✗ | ✗ | ✓ (encrypted) |
| Admin API | ✗ | ✓ | ✗ |
| `get_connection()` | AIADMIN or End User | AIADMIN or End User | End User only |
| `set_agent_context()` | Switches pool | Switches pool | No-op (always End User) |

### Connection Routing by Mode

**standalone/admin mode:**
- `set_agent_context(agent_id)` → End User connection (Data Grant filtered)
- `set_agent_context(None)` → AIADMIN pool (unrestricted)

**agent mode:**
- `get_connection()` → Always returns End User connection from agent_config.json
- No AIADMIN pool initialized
- `set_agent_context()` is a no-op (context is always the configured End User)
