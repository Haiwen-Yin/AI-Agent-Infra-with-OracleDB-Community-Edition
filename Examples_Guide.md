# 📚 Oracle AI Database Memory System v1.0.0 - Examples Guide

> **Complete usage examples and patterns for the Oracle AI Database Memory System**
> 
> **Version:** v1.0.0 Production Release  
> **Author:** 胖头鱼 🐟  
> **Last Updated:** 2024-12-19  
> **Status:** Production Ready ✅

## Table of Contents

1. [Quick Start Examples](#quick-start-examples)
2. [Memory Operations](#memory-operations)
3. [Knowledge Base Operations](#knowledge-base-operations)
4. [Graph Operations](#graph-operations)
5. [Search Operations](#search-operations)
6. [Advanced Patterns](#advanced-patterns)
7. [Multi-Agent Scenarios](#multi-agent-scenarios)
8. [Performance Patterns](#performance-patterns)
9. [Error Handling](#error-handling)
10. [Best Practices](#best-practices)

---

## Quick Start Examples

### 1. Basic Memory Creation

**Python Example:**

```python
from knowledge_base_api import OracleMemorySystem

# Initialize the system
system = OracleMemorySystem(
    host="10.10.10.130",
    port=1521,
    service_name="openclaw",
    user="openclaw",
    password="hermes"
)

# Create a simple memory
result = system.create_memory(
    content="Oracle AI Database supports advanced vector operations",
    memory_type="experience",
    tags=["oracle", "vector", "database"],
    metadata={"source": "documentation", "version": "26ai"},
    embedding_model="bge-m3"
)

print(f"Memory created with ID: {result}")
```

**SQL Example:**

```sql
-- Direct SQL insertion
INSERT INTO memories (
    content, memory_type, tags, metadata, embedding_vector
) VALUES (
    'Oracle AI Database supports advanced vector operations',
    'experience',
    '["oracle", "vector", "database"]',
    '{"source": "documentation", "version": "26ai"}',
    -- BGE-M3 embedding vector (1024 dimensions)
    TO_VECTOR('[0.1, 0.2, 0.3, ...]', 1024, 32, 'FLOAT32')
);

-- Get the inserted memory ID
SELECT memory_id FROM memories 
WHERE content = 'Oracle AI Database supports advanced vector operations'
AND ROWNUM = 1;
```

### 2. Basic Concept Creation

**Python Example:**

```python
# Create a knowledge concept
concept_id = system.create_concept(
    name="Oracle Vector Operations",
    concept_type="technology",
    description="Advanced vector data type operations in Oracle AI Database",
    properties={
        "version": "26ai",
        "features": ["similarity_search", "vector_index", "distance_metrics"],
        "performance": "high"
    },
    tags=["oracle", "vector", "advanced"],
    embedding_model="bge-m3"
)

print(f"Concept created with ID: {concept_id}")
```

**SQL Example:**

```sql
-- Direct SQL insertion
INSERT INTO knowledge_concepts (
    name, concept_type, description, properties, tags, embedding_vector
) VALUES (
    'Oracle Vector Operations',
    'technology',
    'Advanced vector data type operations in Oracle AI Database',
    '{"version": "26ai", "features": ["similarity_search", "vector_index", "distance_metrics"], "performance": "high"}',
    '["oracle", "vector", "advanced"]',
    -- BGE-M3 embedding vector
    TO_VECTOR('[0.15, 0.25, 0.35, ...]', 1024, 32, 'FLOAT32')
);
```

### 3. Creating Relationships

**Python Example:**

```python
# Create a relationship between concepts
rel_id = system.create_relationship(
    source_concept_id=1,
    target_concept_id=2,
    relationship_type="implements",
    properties={
        "strength": 0.9,
        "evidence": "documentation",
        "confidence": "high"
    },
    tags=["implementation", "technology"]
)

print(f"Relationship created with ID: {rel_id}")
```

**SQL Example:**

```sql
-- Direct SQL insertion
INSERT INTO knowledge_relationships (
    source_concept_id, target_concept_id, relationship_type, properties, tags
) VALUES (
    1, 2, 'implements',
    '{"strength": 0.9, "evidence": "documentation", "confidence": "high"}',
    '["implementation", "technology"]'
);
```

---

## Memory Operations

### 1. Memory Retrieval

**Python Example:**

```python
# Get memory by ID
memory = system.get_memory(memory_id=1)
print(f"Content: {memory['content']}")
print(f"Type: {memory['memory_type']}")
print(f"Tags: {memory['tags']}")

# Get memories by type
memories = system.get_memories_by_type(
    memory_type="experience",
    limit=10
)

for mem in memories:
    print(f"Memory {mem['memory_id']}: {mem['content'][:50]}...")
```

**SQL Example:**

```sql
-- Get memory by ID
SELECT * FROM memories WHERE memory_id = 1;

-- Get memories by type
SELECT memory_id, content, memory_type, tags
FROM memories
WHERE memory_type = 'experience'
ORDER BY created_at DESC
FETCH FIRST 10 ROWS ONLY;
```

### 2. Memory Update

**Python Example:**

```python
# Update memory content
system.update_memory(
    memory_id=1,
    content="Updated content with more details",
    tags=["updated", "oracle", "vector"],
    metadata={"version": "2.0", "last_modified": "2024-12-19"}
)

# Update memory metadata only
system.update_memory_metadata(
    memory_id=1,
    metadata={
        "usage_count": 15,
        "last_accessed": "2024-12-19T10:30:00Z",
        "importance_score": 0.85
    }
)
```

**SQL Example:**

```sql
-- Update memory content
UPDATE memories 
SET content = 'Updated content with more details',
    tags = '["updated", "oracle", "vector"]',
    metadata = '{"version": "2.0", "last_modified": "2024-12-19"}',
    updated_at = SYSTIMESTAMP
WHERE memory_id = 1;

-- Update memory metadata only
UPDATE memories 
SET metadata = JSON_MERGEPATCH(
    metadata,
    '{"usage_count": 15, "last_accessed": "2024-12-19T10:30:00Z", "importance_score": 0.85}'
)
WHERE memory_id = 1;
```

### 3. Memory Deletion

**Python Example:**

```python
# Soft delete memory (marks as archived)
system.delete_memory(memory_id=1, soft_delete=True)

# Hard delete memory (permanently removes)
system.delete_memory(memory_id=1, soft_delete=False)

# Delete multiple memories
system.delete_memories(memory_ids=[1, 2, 3], soft_delete=True)
```

**SQL Example:**

```sql
-- Soft delete (archive)
UPDATE memories 
SET status = 'archived',
    updated_at = SYSTIMESTAMP
WHERE memory_id = 1;

-- Hard delete
DELETE FROM memories WHERE memory_id = 1;

-- Delete multiple
DELETE FROM memories WHERE memory_id IN (1, 2, 3);
```

---

## Knowledge Base Operations

### 1. Concept Management

**Python Example:**

```python
# Create concept with full properties
concept_id = system.create_concept(
    name="PostgreSQL 18 Features",
    concept_type="database",
    description="New features in PostgreSQL 18",
    properties={
        "version": "18",
        "features": ["json_table", "incremental_backup", "logical_replication"],
        "performance": "excellent",
        "maturity": "stable"
    },
    tags=["postgresql", "database", "features"],
    embedding_model="bge-m3"
)

# Update concept
system.update_concept(
    concept_id=concept_id,
    description="Updated description with more details",
    properties={
        "version": "18.1",
        "new_features": ["security_patches", "performance_improvements"]
    }
)

# Get concept with all details
concept = system.get_concept(concept_id=concept_id)
print(f"Concept: {concept['name']}")
print(f"Properties: {concept['properties']}")
```

### 2. Experience Distillation

**Python Example:**

```python
# Distill experience from multiple memories
distilled = system.distill_experience(
    memory_ids=[1, 2, 3, 4, 5],
    experience_type="learning",
    title="Oracle Vector Performance Optimization",
    description="Key learnings about optimizing vector operations in Oracle",
    properties={
        "source_memories": [1, 2, 3, 4, 5],
        "confidence_score": 0.92,
        "applicable_contexts": ["performance_tuning", "vector_search"]
    }
)

print(f"Distilled experience ID: {distilled['experience_id']}")
print(f"Title: {distilled['title']}")
```

**SQL Example:**

```sql
-- Manual experience distillation
INSERT INTO knowledge_experiences (
    title, experience_type, description, properties, tags, embedding_vector
)
SELECT 
    'Oracle Vector Performance Optimization',
    'learning',
    'Key learnings about optimizing vector operations in Oracle',
    '{"source_memories": [1, 2, 3, 4, 5], "confidence_score": 0.92}',
    '["optimization", "vector", "performance"]',
    -- Generate embedding from combined content
    (SELECT embedding_vector FROM memories WHERE memory_id = 1)
FROM dual;
```

### 3. Graph Analytics

**Python Example:**

```python
# Get concept relationships
relationships = system.get_relationships(
    concept_id=1,
    relationship_type="implements",
    direction="outgoing",
    limit=20
)

for rel in relationships:
    print(f"Relationship: {rel['source']} -> {rel['target']}")
    print(f"Type: {rel['relationship_type']}")
    print(f"Strength: {rel['strength']}")

# Get graph metrics
metrics = system.get_graph_metrics()
print(f"Total concepts: {metrics['total_concepts']}")
print(f"Total relationships: {metrics['total_relationships']}")
print(f"Average connections: {metrics['avg_connections']}")
```

---

## Graph Operations

### 1. Property Graph Queries

**SQL Example using Oracle Property Graph:**

```sql
-- Create Property Graph
CREATE PROPERTY GRAPH memory_property_graph
  VERTEX TABLES (
    knowledge_concepts AS concept
      KEY (concept_id)
      PROPERTIES (concept_id, name, concept_type, description, properties, tags)
  )
  EDGE TABLES (
    knowledge_relationships AS implements
      KEY (relationship_id)
      SOURCE KEY (source_concept_id) REFERENCES concept (concept_id)
      DESTINATION KEY (target_concept_id) REFERENCES concept (concept_id)
      PROPERTIES (relationship_id, relationship_type, properties, tags)
  );

-- Query using PGQL
SELECT 
  c1.name AS source_name,
  r.relationship_type,
  c2.name AS target_name,
  r.properties
FROM GRAPH TABLE (memory_property_graph MATCH
  (c1:concept)-[r:implements]->(c2:concept)
  WHERE c1.concept_type = 'technology'
  AND r.relationship_type = 'implements'
) AS g;
```

### 2. Graph Traversal

**Python Example:**

```python
# Find all related concepts (BFS traversal)
related = system.traverse_graph(
    start_concept_id=1,
    max_depth=3,
    relationship_types=["implements", "depends_on", "related_to"]
)

for concept in related:
    print(f"Depth {concept['depth']}: {concept['name']}")

# Find shortest path between concepts
path = system.find_path(
    start_concept_id=1,
    end_concept_id=10,
    max_depth=5
)

print(f"Path found: {len(path)} hops")
for node in path:
    print(f"  -> {node['name']}")
```

### 3. Graph Analytics

**SQL Example:**

```sql
-- PageRank calculation (using built-in function)
SELECT 
  concept_id,
  name,
  pagerank_score
FROM (
  SELECT 
    concept_id,
    name,
    PAGERANK(concept_id) OVER () AS pagerank_score
  FROM knowledge_concepts
)
WHERE pagerank_score > 0.01
ORDER BY pagerank_score DESC;

-- Community detection
SELECT 
  concept_id,
  name,
  community_id
FROM (
  SELECT 
    concept_id,
    name,
    LOUVAIN_COMMUNITY(concept_id) OVER () AS community_id
  FROM knowledge_concepts
)
ORDER BY community_id, concept_id;
```

---

## Search Operations

### 1. Vector Similarity Search

**Python Example:**

```python
# Search similar memories
results = system.search_similar_memories(
    query_text="Oracle vector optimization",
    memory_type="experience",
    limit=10,
    similarity_threshold=0.7,
    embedding_model="bge-m3"
)

for result in results:
    print(f"Memory ID: {result['memory_id']}")
    print(f"Similarity: {result['similarity_score']:.4f}")
    print(f"Content: {result['content'][:100]}...")
    print("---")
```

**SQL Example:**

```sql
-- Direct vector similarity search
SELECT 
  memory_id,
  content,
  memory_type,
  tags,
  VECTOR_SIMILARITY(embedding_vector, 
    TO_VECTOR('[0.1, 0.2, 0.3, ...]', 1024, 32, 'FLOAT32'),
    'COSINE',
    10
  ) AS similarity_score
FROM memories
WHERE memory_type = 'experience'
AND status = 'active'
ORDER BY similarity_score DESC;
```

### 2. Hybrid Search

**Python Example:**

```python
# Combined keyword + vector search
results = system.hybrid_search(
    query_text="Oracle performance tuning",
    keywords=["oracle", "performance", "optimization"],
    memory_types=["experience", "observation"],
    limit=20,
    vector_weight=0.7,
    keyword_weight=0.3
)

for result in results:
    print(f"ID: {result['memory_id']}")
    print(f"Combined Score: {result['combined_score']:.4f}")
    print(f"Vector Score: {result['vector_score']:.4f}")
    print(f"Keyword Score: {result['keyword_score']:.4f}")
```

**SQL Example:**

```sql
-- Hybrid search using full-text + vector
WITH vector_results AS (
  SELECT 
    memory_id,
    content,
    VECTOR_SIMILARITY(embedding_vector, 
      TO_VECTOR('[0.1, 0.2, 0.3, ...]', 1024, 32, 'FLOAT32'),
      'COSINE',
      20
    ) AS vector_score
  FROM memories
  WHERE status = 'active'
),
keyword_results AS (
  SELECT 
    memory_id,
    content,
    SCORE(1) AS keyword_score
  FROM memories
  WHERE CONTAINS(content, 'oracle AND performance AND tuning', 1) > 0
  AND status = 'active'
)
SELECT 
  v.memory_id,
  v.content,
  (v.vector_score * 0.7 + k.keyword_score * 0.3) AS combined_score
FROM vector_results v
JOIN keyword_results k ON v.memory_id = k.memory_id
ORDER BY combined_score DESC;
```

### 3. Concept Search

**Python Example:**

```python
# Search concepts by similarity
results = system.search_concepts(
    query_text="database performance",
    concept_type="technology",
    limit=15,
    similarity_threshold=0.6
)

for concept in results:
    print(f"Concept: {concept['name']}")
    print(f"Similarity: {concept['similarity_score']:.4f}")
    print(f"Type: {concept['concept_type']}")
```

---

## Advanced Patterns

### 1. Batch Operations

**Python Example:**

```python
# Batch create memories
memories_data = [
    {
        "content": "Memory 1 content",
        "memory_type": "observation",
        "tags": ["batch", "test"],
        "metadata": {"batch_id": 1}
    },
    {
        "content": "Memory 2 content",
        "memory_type": "experience",
        "tags": ["batch", "production"],
        "metadata": {"batch_id": 1}
    },
    # ... more memories
]

results = system.batch_create_memories(memories_data)
print(f"Created {len(results)} memories")

# Batch create relationships
relationships_data = [
    {
        "source_concept_id": 1,
        "target_concept_id": 2,
        "relationship_type": "depends_on",
        "properties": {"strength": 0.8}
    },
    # ... more relationships
]

results = system.batch_create_relationships(relationships_data)
print(f"Created {len(results)} relationships")
```

**SQL Example:**

```sql
-- Batch insert using FORALL
DECLARE
  TYPE memory_rec IS RECORD (
    content VARCHAR2(4000),
    memory_type VARCHAR2(50),
    tags CLOB,
    metadata CLOB
  );
  TYPE memory_tab IS TABLE OF memory_rec;
  l_memories memory_tab;
BEGIN
  -- Initialize collection
  l_memories := memory_tab();
  l_memories.EXTEND(3);
  
  l_memories(1).content := 'Memory 1';
  l_memories(1).memory_type := 'observation';
  l_memories(1).tags := '["batch"]';
  l_memories(1).metadata := '{}';
  
  l_memories(2).content := 'Memory 2';
  l_memories(2).memory_type := 'experience';
  l_memories(2).tags := '["batch"]';
  l_memories(2).metadata := '{}';
  
  l_memories(3).content := 'Memory 3';
  l_memories(3).memory_type := 'reflection';
  l_memories(3).tags := '["batch"]';
  l_memories(3).metadata := '{}';
  
  FORALL i IN 1..l_memories.COUNT
    INSERT INTO memories (content, memory_type, tags, metadata)
    VALUES (l_memories(i).content, l_memories(i).memory_type,
            l_memories(i).tags, l_memories(i).metadata);
END;
```

### 2. Transaction Patterns

**Python Example:**

```python
# Transactional operations
with system.transaction():
    # Create memory
    memory_id = system.create_memory(
        content="Transaction test",
        memory_type="experience"
    )
    
    # Create related concept
    concept_id = system.create_concept(
        name="Transaction Concept",
        concept_type="concept"
    )
    
    # Create relationship
    system.create_relationship(
        source_concept_id=memory_id,
        target_concept_id=concept_id,
        relationship_type="describes"
    )
    
    # If any operation fails, all are rolled back
```

### 3. Version Control

**Python Example:**

```python
# Create versioned concept
concept_id = system.create_concept(
    name="Versioned Concept",
    concept_type="versioned",
    enable_versioning=True
)

# Update creates new version
system.update_concept(
    concept_id=concept_id,
    content="Updated content",
    create_version=True,
    version_comment="Added new details"
)

# Get version history
versions = system.get_version_history(
    entity_type="concept",
    entity_id=concept_id
)

for version in versions:
    print(f"Version {version['version_number']}: {version['comment']}")
```

---

## Multi-Agent Scenarios

### 1. Agent Session Management

**Python Example:**

```python
# Create agent session
session_id = system.create_agent_session(
    agent_name="oracle_expert",
    session_type="exploration",
    metadata={
        "user_id": "user_123",
        "task": "database_analysis"
    }
)

# Add memories to session
system.add_session_memory(
    session_id=session_id,
    content="Starting database analysis",
    memory_type="observation"
)

# End session and persist memories
system.end_agent_session(
    session_id=session_id,
    persist_memories=True,
    archive_session=False
)
```

### 2. Multi-Agent Collaboration

**Python Example:**

```python
# Create shared memory space
shared_space = system.create_shared_memory_space(
    name="project_collaboration",
    agents=["agent_1", "agent_2", "agent_3"],
    permissions={
        "agent_1": ["read", "write"],
        "agent_2": ["read", "write"],
        "agent_3": ["read"]
    }
)

# Agent 1 adds knowledge
system.add_to_shared_space(
    space_id=shared_space,
    agent_id="agent_1",
    content="Oracle analysis complete",
    memory_type="experience"
)

# Agent 2 reads shared knowledge
memories = system.get_shared_memories(
    space_id=shared_space,
    agent_id="agent_2"
)
```

---

## Performance Patterns

### 1. Connection Pooling

**Python Example:**

```python
# Initialize with connection pooling
system = OracleMemorySystem(
    host="10.10.10.130",
    port=1521,
    service_name="openclaw",
    user="openclaw",
    password="hermes",
    min_connections=5,
    max_connections=20,
    connection_timeout=30
)

# Reuse connections automatically
for i in range(100):
    result = system.get_memory(memory_id=i)
    # Connection is reused from pool
```

### 2. Batch Processing

**Python Example:**

```python
# Batch process large datasets
batch_size = 1000
total_records = 50000

for offset in range(0, total_records, batch_size):
    batch = system.get_memories_batch(
        offset=offset,
        limit=batch_size
    )
    
    # Process batch
    for memory in batch:
        # Perform operations
        pass
    
    print(f"Processed {offset + len(batch)}/{total_records}")
```

### 3. Caching

**Python Example:**

```python
from functools import lru_cache

# Cache frequently accessed data
@lru_cache(maxsize=1000)
def get_cached_concept(concept_id):
    return system.get_concept(concept_id=concept_id)

# Use cached version
concept = get_cached_concept(concept_id=1)

# Clear cache when needed
get_cached_concept.cache_clear()
```

---

## Error Handling

### 1. Basic Error Handling

**Python Example:**

```python
from knowledge_base_api import OracleMemorySystem, OracleMemoryError

try:
    # Perform operation
    memory_id = system.create_memory(
        content="Test memory",
        memory_type="experience"
    )
except OracleMemoryError as e:
    print(f"Memory system error: {e.message}")
    print(f"Error code: {e.error_code}")
except Exception as e:
    print(f"Unexpected error: {str(e)}")
```

### 2. Retry Logic

**Python Example:**

```python
import time
from functools import wraps

def retry_on_failure(max_retries=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    print(f"Attempt {attempt + 1} failed: {e}")
                    time.sleep(delay * (2 ** attempt))
            return None
        return wrapper
    return decorator

@retry_on_failure(max_retries=3, delay=1)
def create_memory_with_retry(content, memory_type):
    return system.create_memory(content=content, memory_type=memory_type)
```

---

## Best Practices

### 1. Memory Design

```python
# ✅ Good: Structured memory with clear context
memory = {
    "content": "Oracle AI Database 26ai introduced VECTOR type with 1024 dimensions",
    "memory_type": "observation",
    "tags": ["oracle", "vector", "database", "26ai"],
    "metadata": {
        "source": "official_documentation",
        "confidence": 0.95,
        "last_verified": "2024-12-19",
        "applicable_versions": ["26ai", "26.1"]
    }
}

# ❌ Bad: Vague memory without context
memory = {
    "content": "Oracle has vectors",
    "memory_type": "observation"
}
```

### 2. Tag Strategy

```python
# ✅ Good: Hierarchical tags
tags = [
    "technology:database:oracle",
    "feature:vector",
    "version:26ai",
    "use_case:similarity_search"
]

# ❌ Bad: Flat, unclear tags
tags = ["oracle", "database", "vector", "stuff"]
```

### 3. Relationship Design

```python
# ✅ Good: Clear relationship with evidence
relationship = {
    "source_concept_id": 1,
    "target_concept_id": 2,
    "relationship_type": "implements",
    "properties": {
        "strength": 0.9,
        "evidence": "Oracle documentation",
        "confidence": "high",
        "created_by": "expert_review"
    }
}

# ❌ Bad: Vague relationship without context
relationship = {
    "source_concept_id": 1,
    "target_concept_id": 2,
    "relationship_type": "related"
}
```

### 4. Search Optimization

```python
# ✅ Good: Specific search with filters
results = system.search_similar_memories(
    query_text="Oracle vector performance optimization techniques",
    memory_type="experience",
    tags=["oracle", "performance"],
    limit=10,
    similarity_threshold=0.8,
    embedding_model="bge-m3"
)

# ❌ Bad: Broad search without filters
results = system.search_similar_memories(
    query_text="Oracle",
    limit=100
)
```

### 5. Batch Operations

```python
# ✅ Good: Batch with error handling
try:
    results = system.batch_create_memories(memories_data)
    print(f"Created {len(results)} memories")
except Exception as e:
    print(f"Batch operation failed: {e}")
    # Implement fallback logic

# ❌ Bad: Individual operations in loop
for memory_data in memories_data:
    try:
        result = system.create_memory(**memory_data)
    except Exception:
        pass  # Silent failure
```

---

## Conclusion

This examples guide covers the most common use cases and patterns for the Oracle AI Database Memory System. For more detailed information, refer to:

- **API Reference:** `API_Reference.md`
- **Design Document:** `knowledge-base-design.md`
- **Performance Guide:** `Performance_Optimization.md`
- **README:** `README_KNOWLEDGE_BASE.md`

**Key Takeaways:**

1. **Always use structured data** with clear context
2. **Implement proper error handling** for production use
3. **Use batch operations** for performance
4. **Leverage caching** for frequently accessed data
5. **Follow tag conventions** for better organization
6. **Use transactions** for critical operations
7. **Monitor performance** regularly

---

**Version History:**

- v1.0.0 (2024-12-19): Initial comprehensive examples guide
- Includes: Basic operations, advanced patterns, multi-agent scenarios, performance patterns

---

**Support & Feedback:**

For questions or issues:
- GitHub Issues: https://github.com/Haiwen-Yin/oracle-memory-system/issues
- Documentation: `README_KNOWLEDGE_BASE.md`

**Author:** 胖头鱼 🐟 (Haiwen Yin)

---

*This document is part of Oracle AI Database Memory System v1.0.0 Production Release*
