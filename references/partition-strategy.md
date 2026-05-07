# Partition Strategy - v0.4.0 Unified Multi-Table Design

**Author**: Haiwen Yin (胖头鱼 🐟)  
**Version**: v0.4.0  
**Last Updated**: 2026-04-29

---

## 🎯 Design Principle

```
Unified partition paradigm: LIST(business dimension) + RANGE(time)

L1 LIST partition → Bucketed by business dimension (hot/warm/cold)
L2 RANGE subpartition → Archived by time (quarterly/monthly)
```

---

## 📊 Partition Plan by Table

### MEMORIES (Main Table - Partition Reference Standard)

| Layer | Type | Column | Values | Purpose |
|-------|------|--------|--------|---------|
| **L1** | LIST | PRIORITY | 1=hot, 2=warm, 3=cold | Hot/Warm/Cold separation |
| **L2** | RANGE SUBPARTITION | CREATED_AT | Q2/Q3/Q4/Future | Quarterly archival |

```sql
CREATE TABLE memories_partitioned (
    ID           NUMBER PRIMARY KEY,
    CONTENT      CLOB,
    MEMORY_TYPE  VARCHAR2(100),
    CATEGORY     VARCHAR2(100),
    PRIORITY     NUMBER,
    CREATED_AT   TIMESTAMP WITH TIME ZONE,
    UPDATED_AT   TIMESTAMP WITH TIME ZONE,
    EXPIRES_AT   TIMESTAMP WITH TIME ZONE,
    TAGS         CLOB,
    METADATA     CLOB
) PARTITION BY LIST (PRIORITY)
  SUBPARTITION BY RANGE (CREATED_AT)
  SUBPARTITION TEMPLATE (
    SUBPARTITION p2026q2 VALUES LESS THAN (TO_DATE('2026-07-01','YYYY-MM-DD')),
    SUBPARTITION p2026q3 VALUES LESS THAN (TO_DATE('2026-10-01','YYYY-MM-DD')),
    SUBPARTITION p2026q4 VALUES LESS THAN (TO_DATE('2027-01-01','YYYY-MM-DD')),
    SUBPARTITION p_future VALUES LESS THAN (MAXVALUE)
  )
  (
    PARTITION p_hot VALUES (1),
    PARTITION p_warm VALUES (2),
    PARTITION p_cold VALUES (3)
  );
```

**Partition Structure:**
```
p_hot (PRIORITY=1)
  ├── p_hot_p2026q2  (CREATED_AT < 2026-07-01)
  ├── p_hot_p2026q3  (CREATED_AT < 2026-10-01)
  ├── p_hot_p2026q4  (CREATED_AT < 2027-01-01)
  └── p_hot_p_future (CREATED_AT >= 2027-01-01)

p_warm (PRIORITY=2)
  ├── p_warm_p2026q2
  ├── p_warm_p2026q3
  ├── p_warm_p2026q4
  └── p_warm_p_future

p_cold (PRIORITY=3)
  ├── p_cold_p2026q2
  ├── p_cold_p2026q3
  ├── p_cold_p2026q4
  └── p_cold_p_future
```

### MEMORY_NODES (Single Layer - No Time Column)

| Layer | Type | Column | Values | Purpose |
|-------|------|--------|--------|---------|
| **L1** | LIST | NODE_TYPE | Core/Test types | Type-based separation |

```sql
CREATE TABLE memory_nodes_partitioned (
    NODE_ID      NUMBER PRIMARY KEY,
    LABEL        VARCHAR2(100),
    NODE_TYPE    VARCHAR2(50),
    PROPERTIES   CLOB,
    EMBEDDING    VECTOR(1024, *)
) PARTITION BY LIST (NODE_TYPE)
  (
    PARTITION p_core VALUES ('Database','Feature','KnowledgeArea','SystemComponent'),
    PARTITION p_test VALUES (DEFAULT)  -- All test_* types
  );
```

### MEMORY_EDGES (Single Layer - No Time Column)

| Layer | Type | Column | Values | Purpose |
|-------|------|--------|--------|---------|
| **L1** | LIST | EDGE_TYPE | Relationship types | Type-based separation |

```sql
CREATE TABLE memory_edges_partitioned (
    EDGE_ID      NUMBER PRIMARY KEY,
    SOURCE_NODE  NUMBER REFERENCES memory_nodes_partitioned(NODE_ID),
    TARGET_NODE  NUMBER REFERENCES memory_nodes_partitioned(NODE_ID),
    EDGE_TYPE    VARCHAR2(100),
    PROPERTIES   CLOB
) PARTITION BY LIST (EDGE_TYPE)
  (
    PARTITION p_supports VALUES ('SUPPORTS','ENABLED_BY'),
    PARTITION p_structure VALUES ('INCLUDES','MANAGES'),
    PARTITION p_other VALUES (DEFAULT)
  );
```

### MEMORY_RELATIONSHIPS (Single Layer - No Time Column)

| Layer | Type | Column | Values | Purpose |
|-------|------|--------|--------|---------|
| **L1** | LIST | RELATIONSHIP_TYPE | Relationship types | Type-based separation |

```sql
CREATE TABLE memory_relationships_partitioned (
    ID                NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    SOURCE_MEMORY_ID  NUMBER NOT NULL,
    TARGET_MEMORY_ID  NUMBER NOT NULL,
    RELATIONSHIP_TYPE VARCHAR2(100),
    CONFIDENCE        NUMBER DEFAULT 1.0,
    CREATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    UNIQUE (SOURCE_MEMORY_ID, TARGET_MEMORY_ID, RELATIONSHIP_TYPE)
) PARTITION BY LIST (RELATIONSHIP_TYPE)
  (
    PARTITION p_similarity VALUES ('SIMILAR_TO','SIMILAR_EMBEDDING','KNOWS'),
    PARTITION p_structure VALUES ('CONTAINS','EXPANDS_ON','PART_OF_SYSTEM'),
    PARTITION p_other VALUES (DEFAULT)
  );
```

---

## 📊 Partition Summary

| Table | L1 LIST | L2 RANGE SUB | Partition Key | Notes |
|-------|---------|--------------|---------------|-------|
| **MEMORIES** | PRIORITY (1=hot,2=warm,3=cold) | CREATED_AT (by quarter) | PRIORITY + CREATED_AT | Main table, partition reference standard |
| **MEMORY_NODES** | NODE_TYPE | None (no time column) | NODE_TYPE | Single-layer LIST partition |
| **MEMORY_EDGES** | EDGE_TYPE | None | EDGE_TYPE | Single-layer LIST partition |
| **MEMORY_RELATIONSHIPS** | RELATIONSHIP_TYPE | None | RELATIONSHIP_TYPE | Single-layer LIST partition |

---

## ⚠️ Execution Considerations

### Migration Steps

```
1. CREATE new partitioned table (CTAS or CREATE TABLE with partitioning)
2. INSERT data from old table (INSERT INTO new_table SELECT * FROM old_table)
3. DROP old table (DROP TABLE old_table)
4. RENAME new table (ALTER TABLE new_table RENAME TO old_table)
5. Recreate indexes, constraints, triggers
6. Recreate JRD views and graph views
7. Verify all functionality
```

### Timing Recommendation

```
⚠ Current data volume is very small (5-14 rows), partition benefits only become evident at 10K+ rows
✅ Recommendation: Document the plan first, execute migration when data reaches 1K+ rows
```

### Risk Assessment

```
Low risk:
- Single-layer LIST partition (MEMORY_NODES, MEMORY_EDGES, MEMORY_RELATIONSHIPS)
- No subpartitions, simple migration

Medium risk:
- Two-layer LIST + RANGE subpartitioning (MEMORIES)
- Requires handling time-based subpartitions
- Requires rebuilding all foreign key constraints
```

---

## 🧪 Test Results (v0.3.1 - 2026-04-23)

### ✅ Verified Features

| Feature | Status | Notes |
|---------|--------|-------|
| **Basic Table Creation** | ✅ PASS | Standard table schema works fine |
| **VECTOR Column Support** | ✅ PASS | VECTOR(1024) type fully functional |
| **HNSW Index Creation** | ⚠️ SEE NOTES | Requires manual creation via DBMS_VECTOR |

### ⚠️ Known Limitations (Oracle AI DB 26ai v23.26.1)

#### LIST + RANGE SUBPARTITION Syntax
- **Status**: Syntax compatibility issue detected
- **Error**: ORA-00906: missing left parenthesis
- **Workaround**: Use standalone LIST or RANGE partitioning instead of combined subpartitioning

#### DATE Literal Format
- **Issue**: Oracle AI DB 26ai requires specific date literal format
- **Correct Syntax**: `VALUES LESS THAN (TO_DATE('2027-01-01', 'YYYY-MM-DD'))`
- **Alternative**: Use MAXVALUE for open-ended partitions

### 📋 Recommended Implementation Approach

Given the limitations, we recommend:

**Option A: Simple LIST Partitioning** (Recommended for v0.3.1)
```sql
CREATE TABLE memories (
    -- columns...
)
PARTITION BY LIST (priority)
(
    PARTITION p_high VALUES IN (1, 2),
    PARTITION p_medium VALUES IN (3),
    PARTITION p_low VALUES IN (4, 5)
);
```

**Option B: RANGE Partitioning by Time**
```sql
CREATE TABLE memories (
    -- columns...
)
PARTITION BY RANGE (created_at)
(
    PARTITION p_2026 VALUES LESS THAN (TO_DATE('2027-01-01', 'YYYY-MM-DD')),
    PARTITION p_future VALUES LESS THAN (MAXVALUE)
);
```

**Option C: LIST + RANGE SUBPARTITIONING** (Full implementation - v0.3.1)
```sql
CREATE TABLE memories (
    -- columns...
)
PARTITION BY LIST (priority)
SUBPARTITION BY RANGE (created_at)
SUBPARTITION TEMPLATE (
    SUBPARTITION p1 VALUES LESS THAN (TO_DATE('2026-07-01', 'YYYY-MM-DD')),
    SUBPARTITION p2 VALUES LESS THAN (TO_DATE('2026-10-01', 'YYYY-MM-DD')),
    SUBPARTITION p3 VALUES LESS THAN (TO_DATE('2027-01-01', 'YYYY-MM-DD')),
    SUBPARTITION p4 VALUES LESS THAN (MAXVALUE)
)
(
    PARTITION p_high VALUES IN (1, 2),
    PARTITION p_medium VALUES IN (3),
    PARTITION p_low VALUES IN (4, 5)
);
```

---

## 📊 Performance Expectations

| Metric | Before Partitioning | After Partitioning | Improvement |
|--------|---------------------|-------------------|-------------|
| **Priority-based queries** | Full table scan | Partition elimination | 3-10x |
| **Time-range queries** | Full table scan | Subpartition pruning | 5-15x |
| **Cold data archival** | Manual DELETE + rebuild | Partition DROP | 10-50x |
| **Backup efficiency** | Full backup | Partition-level backup | 3-5x |

---

## 📚 References

- [Oracle Partitioning Documentation](https://docs.oracle.com/en/database/oracle/oracle-database/23/sqlrf/CREATE-TABLE.html#GUID-F9ADDBAE-1BE3-4EA4-A74E-7240A98E1AB0)
- [Oracle LIST Partitioning](https://docs.oracle.com/en/database/oracle/oracle-database/23/vldbg/partition-concepts.html#GUID-8E5E22C2-0318-481B-827B-F8FFDBB2A8AB)
- [Oracle RANGE Partitioning](https://docs.oracle.com/en/database/oracle/oracle-database/23/vldbg/partition-concepts.html#GUID-5A4B4AA2-8467-4A53-A1B1-825E8F5B0B06)

---

**Last Updated**: 2026-04-29 v0.4.0
