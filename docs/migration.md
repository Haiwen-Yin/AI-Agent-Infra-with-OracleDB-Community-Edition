# Migration Guide: v1.x → v2.0.0

## Breaking Changes

### Table Mapping
| v1.x Table | v2.0 Table | Notes |
|------------|-----------|-------|
| MEMORIES | ENTITIES | ENTITY_TYPE='MEMORY' |
| MEMORY_NODES | ENTITIES | ENTITY_TYPE='MEMORY' |
| MEMORY_EDGES | ENTITY_EDGES | Unified edge table |
| MEMORY_RELATIONSHIPS | ENTITY_EDGES | Edge type mapping below |
| KNOWLEDGE_CONCEPTS | ENTITIES | ENTITY_TYPE='KNOWLEDGE' |
| KNOWLEDGE_GRAPH | ENTITY_EDGES | Edge type mapping below |
| AGENT_MEMORY_ACCESS | ENTITY_ACCESS_LOG | Extended to all entity types |

### Edge Type Mapping
| v1 Source | v1 Type | v2 Type |
|-----------|---------|---------|
| MEMORY_EDGES | Various | RELATED_TO |
| MEMORY_RELATIONSHIPS | semantic | RELATED_TO / DERIVED_FROM |
| KNOWLEDGE_GRAPH | depends_on | DEPENDS_ON |
| KNOWLEDGE_GRAPH | related_to | RELATED_TO |
| KNOWLEDGE_GRAPH | derived_from | DERIVED_FROM |
| KNOWLEDGE_GRAPH | causes | CAUSES |
| KNOWLEDGE_GRAPH | enables | ENABLES |
| KNOWLEDGE_GRAPH | prevents | PREVENTS |

### Column Renames
| v1 Column | v2 Column | Table |
|-----------|-----------|-------|
| AGENT_COLLABORATION.MEMORY_ID | AGENT_COLLABORATION.MEMORY_ID | Still named MEMORY_ID but references ENTITIES |

### Dropped Objects
- KNOWLEDGE_PROPERTY_GRAPH → ORACLE_MEMORY_GRAPH
- MEMORY_PROPERTY_GRAPH → ORACLE_MEMORY_GRAPH
- MEMORIES_JDV, MEMORY_NODES_JDV, MEMORY_EDGES_JDV → MEMORY_DV
- MEMORIES_WITH_TAGS_JDV, MEMORIES_READONLY_JDV → KNOWLEDGE_DV

## Migration Strategy

### Option 1: Clean Install (Recommended)
Deploy v2.0 schema on fresh database. No data migration needed.

### Option 2: In-Place Migration
1. Export v1 data: `EXPORT SCHEMA ...`
2. Deploy v2.0 schema (Phase 1)
3. Map and insert v1 data into v2.0 tables
4. Deploy v2.0 API (Phase 2) and Jobs (Phase 3)
5. Verify counts match

### Data Migration SQL (for Option 2)

```sql
-- Migrate MEMORIES → ENTITIES
INSERT INTO ENTITIES (ENTITY_TYPE, NAME, CONTENT, CATEGORY, PRIORITY, STATUS, CREATED_AT)
SELECT 'MEMORY', NAME, CONTENT, CATEGORY, PRIORITY, STATUS, CREATED_AT FROM MEMORIES;

-- Migrate MEMORY_NODES → ENTITIES
INSERT INTO ENTITIES (ENTITY_TYPE, NAME, DESCRIPTION, CONTENT, CATEGORY, CREATED_AT)
SELECT 'MEMORY', NODE_NAME, NODE_DESCRIPTION, NODE_CONTENT, NODE_CATEGORY, CREATED_AT
FROM MEMORY_NODES;

-- Migrate KNOWLEDGE_CONCEPTS → ENTITIES + KNOWLEDGE_META
INSERT INTO ENTITIES (ENTITY_TYPE, NAME, DESCRIPTION, CONTENT, CATEGORY, CREATED_AT)
SELECT 'KNOWLEDGE', CONCEPT_NAME, CONCEPT_DESCRIPTION, CONCEPT_CONTENT, CONCEPT_CATEGORY, CREATED_AT
FROM KNOWLEDGE_CONCEPTS;
```

## Python Code Migration

Replace all SQLcl subprocess calls:
```python
# v1.x
import subprocess
result = subprocess.run(['/root/sqlcl/bin/sql', ...], capture_output=True)

# v2.0
from scripts.lib.connection import execute_query
rows = execute_query("SELECT * FROM ENTITIES WHERE ENTITY_TYPE = 'MEMORY'")
```
