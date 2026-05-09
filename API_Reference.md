# 📖 Oracle AI Database Memory System v1.0.0 - API Reference

> **Complete API documentation for Python and SQL interfaces**
> 
> **Version:** v1.0.0 Production Release  
> **Author:** 胖头鱼 🐟  
> **Last Updated:** 2024-12-19  
> **Status:** Production Ready ✅

## Table of Contents

1. [Python API Reference](#python-api-reference)
2. [SQL API Reference](#sql-api-reference)
3. [PL/SQL Package Reference](#plsql-package-reference)
4. [Data Types](#data-types)
5. [Error Codes](#error-codes)
6. [Examples](#examples)

---

## Python API Reference

### OracleMemorySystem Class

**Constructor:**

```python
OracleMemorySystem(
    host: str,
    port: int = 1521,
    service_name: str,
    user: str,
    password: str,
    min_connections: int = 5,
    max_connections: int = 20,
    connection_timeout: int = 30,
    enable_cache: bool = True,
    cache_ttl: int = 300
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| host | str | Required | Oracle database host |
| port | int | 1521 | Database port |
| service_name | str | Required | Oracle service name |
| user | str | Required | Database username |
| password | str | Required | Database password |
| min_connections | int | 5 | Minimum connections in pool |
| max_connections | int | 20 | Maximum connections in pool |
| connection_timeout | int | 30 | Connection timeout in seconds |
| enable_cache | bool | True | Enable query caching |
| cache_ttl | int | 300 | Cache time-to-live in seconds |

---

### Memory Operations

#### create_memory

```python
create_memory(
    content: str,
    memory_type: str,
    tags: List[str] = None,
    metadata: Dict = None,
    embedding_model: str = "bge-m3",
    embedding_vector: List[float] = None,
    status: str = "active"
) -> int
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| content | str | Required | Memory content text |
| memory_type | str | Required | Type: 'experience', 'observation', 'reflection' |
| tags | List[str] | None | List of tags for categorization |
| metadata | Dict | None | Additional metadata as JSON |
| embedding_model | str | "bge-m3" | Embedding model to use |
| embedding_vector | List[float] | None | Pre-computed embedding vector |
| status | str | "active" | Memory status |

**Returns:** `int` - Memory ID

**Example:**

```python
memory_id = system.create_memory(
    content="Oracle 26ai supports vector operations",
    memory_type="experience",
    tags=["oracle", "vector", "database"],
    metadata={"source": "documentation", "version": "26ai"},
    embedding_model="bge-m3"
)
```

---

#### get_memory

```python
get_memory(
    memory_id: int,
    include_embedding: bool = False
) -> Dict
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| memory_id | int | Required | Memory ID to retrieve |
| include_embedding | bool | False | Include embedding vector in result |

**Returns:** `Dict` with keys:
- `memory_id`: int
- `content`: str
- `memory_type`: str
- `tags`: List[str]
- `metadata`: Dict
- `embedding_vector`: List[float] (if include_embedding=True)
- `created_at`: datetime
- `updated_at`: datetime

**Example:**

```python
memory = system.get_memory(memory_id=1)
print(memory['content'])
print(memory['tags'])
```

---

#### update_memory

```python
update_memory(
    memory_id: int,
    content: str = None,
    memory_type: str = None,
    tags: List[str] = None,
    metadata: Dict = None,
    embedding_model: str = "bge-m3",
    status: str = None
) -> bool
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| memory_id | int | Required | Memory ID to update |
| content | str | None | New content text |
| memory_type | str | None | New memory type |
| tags | List[str] | None | New tags list |
| metadata | Dict | None | New metadata (merged with existing) |
| embedding_model | str | "bge-m3" | Embedding model for regeneration |
| status | str | None | New status |

**Returns:** `bool` - True if successful

**Example:**

```python
success = system.update_memory(
    memory_id=1,
    content="Updated content with more details",
    tags=["updated", "oracle"]
)
```

---

#### delete_memory

```python
delete_memory(
    memory_id: int,
    soft_delete: bool = True
) -> bool
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| memory_id | int | Required | Memory ID to delete |
| soft_delete | bool | True | If True, mark as archived; if False, permanently delete |

**Returns:** `bool` - True if successful

**Example:**

```python
# Soft delete (archive)
system.delete_memory(memory_id=1, soft_delete=True)

# Hard delete (permanent)
system.delete_memory(memory_id=1, soft_delete=False)
```

---

#### get_memories_by_type

```python
get_memories_by_type(
    memory_type: str,
    limit: int = 100,
    offset: int = 0
) -> List[Dict]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| memory_type | str | Required | Memory type to filter |
| limit | int | 100 | Maximum results to return |
| offset | int | 0 | Offset for pagination |

**Returns:** `List[Dict]` - List of memory objects

**Example:**

```python
experiences = system.get_memories_by_type(
    memory_type="experience",
    limit=20
)
```

---

### Concept Operations

#### create_concept

```python
create_concept(
    name: str,
    concept_type: str,
    description: str = None,
    properties: Dict = None,
    tags: List[str] = None,
    embedding_model: str = "bge-m3",
    embedding_vector: List[float] = None
) -> int
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| name | str | Required | Concept name |
| concept_type | str | Required | Type: 'technology', 'concept', 'entity', 'process' |
| description | str | None | Concept description |
| properties | Dict | None | Additional properties as JSON |
| tags | List[str] | None | List of tags |
| embedding_model | str | "bge-m3" | Embedding model to use |
| embedding_vector | List[float] | None | Pre-computed embedding vector |

**Returns:** `int` - Concept ID

**Example:**

```python
concept_id = system.create_concept(
    name="Oracle Vector Operations",
    concept_type="technology",
    description="Advanced vector operations in Oracle",
    properties={"version": "26ai", "features": ["similarity_search"]},
    tags=["oracle", "vector"]
)
```

---

#### get_concept

```python
get_concept(
    concept_id: int,
    include_embedding: bool = False
) -> Dict
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| concept_id | int | Required | Concept ID to retrieve |
| include_embedding | bool | False | Include embedding vector |

**Returns:** `Dict` with keys:
- `concept_id`: int
- `name`: str
- `concept_type`: str
- `description`: str
- `properties`: Dict
- `tags`: List[str]
- `embedding_vector`: List[float] (if include_embedding=True)
- `created_at`: datetime
- `updated_at`: datetime

**Example:**

```python
concept = system.get_concept(concept_id=1)
print(concept['name'])
print(concept['properties'])
```

---

#### update_concept

```python
update_concept(
    concept_id: int,
    name: str = None,
    concept_type: str = None,
    description: str = None,
    properties: Dict = None,
    tags: List[str] = None,
    embedding_model: str = "bge-m3"
) -> bool
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| concept_id | int | Required | Concept ID to update |
| name | str | None | New concept name |
| concept_type | str | None | New concept type |
| description | str | None | New description |
| properties | Dict | None | New properties (merged with existing) |
| tags | List[str] | None | New tags list |
| embedding_model | str | "bge-m3" | Embedding model for regeneration |

**Returns:** `bool` - True if successful

**Example:**

```python
success = system.update_concept(
    concept_id=1,
    description="Updated description",
    properties={"version": "26.1"}
)
```

---

#### delete_concept

```python
delete_concept(
    concept_id: int,
    soft_delete: bool = True
) -> bool
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| concept_id | int | Required | Concept ID to delete |
| soft_delete | bool | True | If True, mark as archived; if False, permanently delete |

**Returns:** `bool` - True if successful

**Example:**

```python
system.delete_concept(concept_id=1, soft_delete=True)
```

---

### Relationship Operations

#### create_relationship

```python
create_relationship(
    source_concept_id: int,
    target_concept_id: int,
    relationship_type: str,
    properties: Dict = None,
    tags: List[str] = None,
    strength: float = 1.0
) -> int
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| source_concept_id | int | Required | Source concept ID |
| target_concept_id | int | Required | Target concept ID |
| relationship_type | str | Required | Type: 'implements', 'depends_on', 'related_to' |
| properties | Dict | None | Additional properties |
| tags | List[str] | None | List of tags |
| strength | float | 1.0 | Relationship strength (0.0 to 1.0) |

**Returns:** `int` - Relationship ID

**Example:**

```python
rel_id = system.create_relationship(
    source_concept_id=1,
    target_concept_id=2,
    relationship_type="implements",
    properties={"evidence": "documentation"},
    strength=0.9
)
```

---

#### get_relationships

```python
get_relationships(
    concept_id: int,
    relationship_type: str = None,
    direction: str = "both",
    limit: int = 100
) -> List[Dict]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| concept_id | int | Required | Concept ID to get relationships for |
| relationship_type | str | None | Filter by relationship type |
| direction | str | "both" | 'incoming', 'outgoing', or 'both' |
| limit | int | 100 | Maximum results to return |

**Returns:** `List[Dict]` - List of relationship objects

**Example:**

```python
relationships = system.get_relationships(
    concept_id=1,
    relationship_type="implements",
    direction="outgoing"
)
```

---

#### delete_relationship

```python
delete_relationship(
    relationship_id: int
) -> bool
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| relationship_id | int | Required | Relationship ID to delete |

**Returns:** `bool` - True if successful

**Example:**

```python
system.delete_relationship(relationship_id=1)
```

---

### Search Operations

#### search_similar_memories

```python
search_similar_memories(
    query_text: str = None,
    query_vector: List[float] = None,
    memory_type: str = None,
    tags: List[str] = None,
    limit: int = 10,
    similarity_threshold: float = 0.7,
    embedding_model: str = "bge-m3"
) -> List[Dict]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| query_text | str | None | Text query for embedding generation |
| query_vector | List[float] | None | Pre-computed query vector |
| memory_type | str | None | Filter by memory type |
| tags | List[str] | None | Filter by tags |
| limit | int | 10 | Maximum results to return |
| similarity_threshold | float | 0.7 | Minimum similarity score |
| embedding_model | str | "bge-m3" | Embedding model for query |

**Returns:** `List[Dict]` - List of similar memories with similarity scores

**Example:**

```python
results = system.search_similar_memories(
    query_text="Oracle vector optimization",
    memory_type="experience",
    limit=10,
    similarity_threshold=0.8
)

for result in results:
    print(f"Similarity: {result['similarity_score']:.4f}")
    print(f"Content: {result['content'][:100]}")
```

---

#### search_concepts

```python
search_concepts(
    query_text: str = None,
    query_vector: List[float] = None,
    concept_type: str = None,
    tags: List[str] = None,
    limit: int = 10,
    similarity_threshold: float = 0.7,
    embedding_model: str = "bge-m3"
) -> List[Dict]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| query_text | str | None | Text query for embedding generation |
| query_vector | List[float] | None | Pre-computed query vector |
| concept_type | str | None | Filter by concept type |
| tags | List[str] | None | Filter by tags |
| limit | int | 10 | Maximum results to return |
| similarity_threshold | float | 0.7 | Minimum similarity score |
| embedding_model | str | "bge-m3" | Embedding model for query |

**Returns:** `List[Dict]` - List of similar concepts with similarity scores

**Example:**

```python
results = system.search_concepts(
    query_text="database performance",
    concept_type="technology",
    limit=15
)
```

---

#### hybrid_search

```python
hybrid_search(
    query_text: str,
    keywords: List[str] = None,
    memory_types: List[str] = None,
    limit: int = 20,
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
    embedding_model: str = "bge-m3"
) -> List[Dict]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| query_text | str | Required | Text query |
| keywords | List[str] | None | Keywords for full-text search |
| memory_types | List[str] | None | Filter by memory types |
| limit | int | 20 | Maximum results to return |
| vector_weight | float | 0.7 | Weight for vector similarity |
| keyword_weight | float | 0.3 | Weight for keyword match |
| embedding_model | str | "bge-m3" | Embedding model for query |

**Returns:** `List[Dict]` - List of results with combined scores

**Example:**

```python
results = system.hybrid_search(
    query_text="Oracle performance tuning",
    keywords=["oracle", "performance", "optimization"],
    vector_weight=0.6,
    keyword_weight=0.4
)
```

---

### Experience Distillation

#### distill_experience

```python
distill_experience(
    memory_ids: List[int],
    experience_type: str,
    title: str,
    description: str = None,
    properties: Dict = None,
    tags: List[str] = None
) -> Dict
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| memory_ids | List[int] | Required | Source memory IDs |
| experience_type | str | Required | Type: 'learning', 'insight', 'pattern' |
| title | str | Required | Experience title |
| description | str | None | Experience description |
| properties | Dict | None | Additional properties |
| tags | List[str] | None | List of tags |

**Returns:** `Dict` with distilled experience

**Example:**

```python
experience = system.distill_experience(
    memory_ids=[1, 2, 3, 4, 5],
    experience_type="learning",
    title="Oracle Vector Performance Optimization",
    description="Key learnings about optimizing vector operations",
    properties={"confidence": 0.92}
)
```

---

### Statistics and Metrics

#### get_statistics

```python
get_statistics() -> Dict
```

**Returns:** `Dict` with statistics:
- `total_memories`: int
- `total_concepts`: int
- `total_relationships`: int
- `memories_by_type`: Dict
- `concepts_by_type`: Dict

**Example:**

```python
stats = system.get_statistics()
print(f"Total memories: {stats['total_memories']}")
print(f"Total concepts: {stats['total_concepts']}")
```

---

#### get_graph_metrics

```python
get_graph_metrics() -> Dict
```

**Returns:** `Dict` with graph metrics:
- `total_concepts`: int
- `total_relationships`: int
- `avg_connections`: float
- `max_connections`: int
- `orphaned_concepts`: int

**Example:**

```python
metrics = system.get_graph_metrics()
print(f"Average connections: {metrics['avg_connections']:.2f}")
```

---

#### get_version_history

```python
get_version_history(
    entity_type: str,
    entity_id: int,
    limit: int = 50
) -> List[Dict]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| entity_type | str | Required | 'memory' or 'concept' |
| entity_id | int | Required | Entity ID |
| limit | int | 50 | Maximum versions to return |

**Returns:** `List[Dict]` - List of version history entries

**Example:**

```python
versions = system.get_version_history(
    entity_type="concept",
    entity_id=1
)

for version in versions:
    print(f"Version {version['version_number']}: {version['comment']}")
```

---

### Batch Operations

#### batch_create_memories

```python
batch_create_memories(
    memories_data: List[Dict],
    batch_size: int = 1000
) -> List[int]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| memories_data | List[Dict] | Required | List of memory data dicts |
| batch_size | int | 1000 | Batch size for processing |

**Returns:** `List[int]` - List of created memory IDs

**Example:**

```python
memories = [
    {"content": "Memory 1", "memory_type": "experience"},
    {"content": "Memory 2", "memory_type": "observation"},
    # ... more memories
]

memory_ids = system.batch_create_memories(memories)
```

---

#### batch_create_relationships

```python
batch_create_relationships(
    relationships_data: List[Dict],
    batch_size: int = 1000
) -> List[int]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| relationships_data | List[Dict] | Required | List of relationship data dicts |
| batch_size | int | 1000 | Batch size for processing |

**Returns:** `List[int]` - List of created relationship IDs

**Example:**

```python
relationships = [
    {"source_concept_id": 1, "target_concept_id": 2, "relationship_type": "implements"},
    # ... more relationships
]

rel_ids = system.batch_create_relationships(relationships)
```

---

## SQL API Reference

### Core Tables

#### memories

```sql
CREATE TABLE memories (
    memory_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content CLOB NOT NULL,
    memory_type VARCHAR2(50) NOT NULL,
    tags CLOB,
    metadata CLOB,
    embedding_vector VECTOR(1024, FLOAT32),
    embedding_model VARCHAR2(50) DEFAULT 'bge-m3',
    status VARCHAR2(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
    updated_at TIMESTAMP DEFAULT SYSTIMESTAMP
);
```

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| memory_id | NUMBER | Primary key |
| content | CLOB | Memory content text |
| memory_type | VARCHAR2(50) | Memory type |
| tags | CLOB | JSON array of tags |
| metadata | CLOB | JSON metadata |
| embedding_vector | VECTOR(1024, FLOAT32) | Vector embedding |
| embedding_model | VARCHAR2(50) | Embedding model name |
| status | VARCHAR2(20) | Memory status |
| created_at | TIMESTAMP | Creation timestamp |
| updated_at | TIMESTAMP | Last update timestamp |

---

#### knowledge_concepts

```sql
CREATE TABLE knowledge_concepts (
    concept_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR2(200) NOT NULL,
    concept_type VARCHAR2(50) NOT NULL,
    description CLOB,
    properties CLOB,
    tags CLOB,
    embedding_vector VECTOR(1024, FLOAT32),
    embedding_model VARCHAR2(50) DEFAULT 'bge-m3',
    status VARCHAR2(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
    updated_at TIMESTAMP DEFAULT SYSTIMESTAMP
);
```

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| concept_id | NUMBER | Primary key |
| name | VARCHAR2(200) | Concept name |
| concept_type | VARCHAR2(50) | Concept type |
| description | CLOB | Concept description |
| properties | CLOB | JSON properties |
| tags | CLOB | JSON array of tags |
| embedding_vector | VECTOR(1024, FLOAT32) | Vector embedding |
| embedding_model | VARCHAR2(50) | Embedding model name |
| status | VARCHAR2(20) | Concept status |
| created_at | TIMESTAMP | Creation timestamp |
| updated_at | TIMESTAMP | Last update timestamp |

---

#### knowledge_relationships

```sql
CREATE TABLE knowledge_relationships (
    relationship_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_concept_id NUMBER NOT NULL,
    target_concept_id NUMBER NOT NULL,
    relationship_type VARCHAR2(50) NOT NULL,
    properties CLOB,
    tags CLOB,
    strength NUMBER(5,4) DEFAULT 1.0,
    status VARCHAR2(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
    updated_at TIMESTAMP DEFAULT SYSTIMESTAMP,
    CONSTRAINT fk_mr_source_node 
        FOREIGN KEY (source_concept_id) 
        REFERENCES knowledge_concepts(concept_id),
    CONSTRAINT fk_mr_target_node 
        FOREIGN KEY (target_concept_id) 
        REFERENCES knowledge_concepts(concept_id)
);
```

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| relationship_id | NUMBER | Primary key |
| source_concept_id | NUMBER | Source concept FK |
| target_concept_id | NUMBER | Target concept FK |
| relationship_type | VARCHAR2(50) | Relationship type |
| properties | CLOB | JSON properties |
| tags | CLOB | JSON array of tags |
| strength | NUMBER(5,4) | Relationship strength |
| status | VARCHAR2(20) | Relationship status |
| created_at | TIMESTAMP | Creation timestamp |
| updated_at | TIMESTAMP | Last update timestamp |

---

### Core Views

#### memories_jdv

```sql
CREATE OR REPLACE VIEW memories_jdv AS
SELECT 
    memory_id,
    content,
    memory_type,
    tags,
    metadata,
    embedding_model,
    status,
    created_at,
    updated_at
FROM memories;
```

#### knowledge_concepts_jdv

```sql
CREATE OR REPLACE VIEW knowledge_concepts_jdv AS
SELECT 
    concept_id,
    name,
    concept_type,
    description,
    properties,
    tags,
    embedding_model,
    status,
    created_at,
    updated_at
FROM knowledge_concepts;
```

#### knowledge_relationships_jdv

```sql
CREATE OR REPLACE VIEW knowledge_relationships_jdv AS
SELECT 
    relationship_id,
    source_concept_id,
    target_concept_id,
    relationship_type,
    properties,
    tags,
    strength,
    status,
    created_at,
    updated_at
FROM knowledge_relationships;
```

---

### Core Functions

#### create_memory

```sql
CREATE OR REPLACE FUNCTION create_memory(
    p_content IN CLOB,
    p_memory_type IN VARCHAR2,
    p_tags IN CLOB DEFAULT NULL,
    p_metadata IN CLOB DEFAULT NULL,
    p_embedding_model IN VARCHAR2 DEFAULT 'bge-m3',
    p_embedding_vector IN VECTOR DEFAULT NULL
) RETURN NUMBER
```

**Returns:** `NUMBER` - Memory ID

**Example:**

```sql
DECLARE
    l_memory_id NUMBER;
BEGIN
    l_memory_id := create_memory(
        p_content => 'Oracle 26ai supports vector operations',
        p_memory_type => 'experience',
        p_tags => '["oracle", "vector"]',
        p_metadata => '{"version": "26ai"}'
    );
    DBMS_OUTPUT.PUT_LINE('Memory ID: ' || l_memory_id);
END;
```

---

#### get_memory

```sql
CREATE OR REPLACE FUNCTION get_memory(
    p_memory_id IN NUMBER,
    p_include_embedding IN BOOLEAN DEFAULT FALSE
) RETURN CLOB
```

**Returns:** `CLOB` - JSON representation of memory

**Example:**

```sql
DECLARE
    l_memory CLOB;
BEGIN
    l_memory := get_memory(
        p_memory_id => 1,
        p_include_embedding => TRUE
    );
    DBMS_OUTPUT.PUT_LINE(l_memory);
END;
```

---

#### create_concept

```sql
CREATE OR REPLACE FUNCTION create_concept(
    p_name IN VARCHAR2,
    p_concept_type IN VARCHAR2,
    p_description IN CLOB DEFAULT NULL,
    p_properties IN CLOB DEFAULT NULL,
    p_tags IN CLOB DEFAULT NULL,
    p_embedding_model IN VARCHAR2 DEFAULT 'bge-m3',
    p_embedding_vector IN VECTOR DEFAULT NULL
) RETURN NUMBER
```

**Returns:** `NUMBER` - Concept ID

**Example:**

```sql
DECLARE
    l_concept_id NUMBER;
BEGIN
    l_concept_id := create_concept(
        p_name => 'Oracle Vector Operations',
        p_concept_type => 'technology',
        p_description => 'Advanced vector operations',
        p_properties => '{"version": "26ai"}'
    );
END;
```

---

#### create_relationship

```sql
CREATE OR REPLACE FUNCTION create_relationship(
    p_source_concept_id IN NUMBER,
    p_target_concept_id IN NUMBER,
    p_relationship_type IN VARCHAR2,
    p_properties IN CLOB DEFAULT NULL,
    p_tags IN CLOB DEFAULT NULL,
    p_strength IN NUMBER DEFAULT 1.0
) RETURN NUMBER
```

**Returns:** `NUMBER` - Relationship ID

**Example:**

```sql
DECLARE
    l_rel_id NUMBER;
BEGIN
    l_rel_id := create_relationship(
        p_source_concept_id => 1,
        p_target_concept_id => 2,
        p_relationship_type => 'implements',
        p_strength => 0.9
    );
END;
```

---

#### search_similar_memories

```sql
CREATE OR REPLACE FUNCTION search_similar_memories(
    p_query_vector IN VECTOR,
    p_memory_type IN VARCHAR2 DEFAULT NULL,
    p_limit IN NUMBER DEFAULT 10,
    p_similarity_threshold IN NUMBER DEFAULT 0.7
) RETURN CLOB
```

**Returns:** `CLOB` - JSON array of similar memories

**Example:**

```sql
DECLARE
    l_results CLOB;
    l_query_vector VECTOR(1024, FLOAT32);
BEGIN
    -- Generate query vector (external API call)
    l_query_vector := generate_embedding('Oracle vector optimization');
    
    l_results := search_similar_memories(
        p_query_vector => l_query_vector,
        p_memory_type => 'experience',
        p_limit => 10,
        p_similarity_threshold => 0.8
    );
    DBMS_OUTPUT.PUT_LINE(l_results);
END;
```

---

## PL/SQL Package Reference

### memory_system_pkg

**Package Specification:**

```sql
CREATE OR REPLACE PACKAGE memory_system_pkg AS
    -- Memory Operations
    FUNCTION create_memory(
        p_content IN CLOB,
        p_memory_type IN VARCHAR2,
        p_tags IN CLOB DEFAULT NULL,
        p_metadata IN CLOB DEFAULT NULL
    ) RETURN NUMBER;
    
    FUNCTION get_memory(
        p_memory_id IN NUMBER
    ) RETURN CLOB;
    
    FUNCTION update_memory(
        p_memory_id IN NUMBER,
        p_content IN CLOB DEFAULT NULL,
        p_tags IN CLOB DEFAULT NULL,
        p_metadata IN CLOB DEFAULT NULL
    ) RETURN BOOLEAN;
    
    FUNCTION delete_memory(
        p_memory_id IN NUMBER,
        p_soft_delete IN BOOLEAN DEFAULT TRUE
    ) RETURN BOOLEAN;
    
    -- Concept Operations
    FUNCTION create_concept(
        p_name IN VARCHAR2,
        p_concept_type IN VARCHAR2,
        p_description IN CLOB DEFAULT NULL,
        p_properties IN CLOB DEFAULT NULL
    ) RETURN NUMBER;
    
    FUNCTION get_concept(
        p_concept_id IN NUMBER
    ) RETURN CLOB;
    
    -- Relationship Operations
    FUNCTION create_relationship(
        p_source_concept_id IN NUMBER,
        p_target_concept_id IN NUMBER,
        p_relationship_type IN VARCHAR2,
        p_properties IN CLOB DEFAULT NULL
    ) RETURN NUMBER;
    
    -- Search Operations
    FUNCTION search_similar_memories(
        p_query_vector IN VECTOR,
        p_limit IN NUMBER DEFAULT 10
    ) RETURN CLOB;
    
    -- Statistics
    FUNCTION get_statistics RETURN CLOB;
    
END memory_system_pkg;
```

---

## Data Types

### Vector Types

```sql
-- 1024-dimensional vector (BGE-M3 default)
VECTOR(1024, FLOAT32)

-- 512-dimensional vector (reduced)
VECTOR(512, FLOAT32)

-- 1536-dimensional vector (OpenAI)
VECTOR(1536, FLOAT32)
```

### JSON Types

```sql
-- Tags (JSON array)
'["tag1", "tag2", "tag3"]'

-- Metadata (JSON object)
'{"key": "value", "nested": {"key": "value"}}'

-- Properties (JSON object)
'{"version": "26ai", "features": ["vector", "graph"]}'
```

### Status Types

```sql
-- Memory/Concept status
'active'     -- Default, visible and searchable
'archived'   -- Soft deleted, hidden from search
'deleted'    -- Hard deleted, permanently removed

-- Relationship status
'active'     -- Default, relationship exists
'inactive'   -- Relationship disabled
'deleted'    -- Relationship removed
```

---

## Error Codes

### System Errors

| Code | Description | Solution |
|------|-------------|----------|
| 1000 | Connection failed | Check host/port/service |
| 1001 | Authentication failed | Verify username/password |
| 1002 | Connection pool exhausted | Increase max_connections |
| 1003 | Query timeout | Optimize query or increase timeout |
| 1004 | Memory allocation failed | Increase PGA/SGA |

### Data Errors

| Code | Description | Solution |
|------|-------------|----------|
| 2000 | Invalid memory type | Use valid type: experience, observation, reflection |
| 2001 | Invalid concept type | Use valid type: technology, concept, entity, process |
| 2002 | Invalid relationship type | Use valid type: implements, depends_on, related_to |
| 2003 | Vector dimension mismatch | Ensure vector is 1024 dimensions |
| 2004 | Invalid JSON format | Validate JSON syntax |
| 2005 | Missing required field | Provide all required parameters |

### Search Errors

| Code | Description | Solution |
|------|-------------|----------|
| 3000 | No embedding model | Specify embedding_model parameter |
| 3001 | Embedding generation failed | Check embedding API availability |
| 3002 | Vector index not found | Create vector index on table |
| 3003 | Similarity threshold too high | Lower threshold (0.0 to 1.0) |
| 3004 | Search timeout | Optimize index or reduce limit |

---

## Examples

### Complete Example

```python
from knowledge_base_api import OracleMemorySystem

# Initialize system
system = OracleMemorySystem(
    host="10.10.10.130",
    port=1521,
    service_name="openclaw",
    user="openclaw",
    password="hermes"
)

# Create memory
memory_id = system.create_memory(
    content="Oracle AI Database supports advanced vector operations",
    memory_type="experience",
    tags=["oracle", "vector", "database"],
    metadata={"source": "documentation", "version": "26ai"}
)

# Create concept
concept_id = system.create_concept(
    name="Oracle Vector Operations",
    concept_type="technology",
    description="Advanced vector data type operations",
    properties={"version": "26ai", "features": ["similarity_search"]}
)

# Create relationship
rel_id = system.create_relationship(
    source_concept_id=memory_id,
    target_concept_id=concept_id,
    relationship_type="describes",
    strength=0.9
)

# Search similar memories
results = system.search_similar_memories(
    query_text="Oracle vector optimization",
    memory_type="experience",
    limit=10
)

# Get statistics
stats = system.get_statistics()
print(f"Total memories: {stats['total_memories']}")
```

---

**Version History:**

- v1.0.0 (2024-12-19): Initial API reference
- Includes: Python API, SQL API, PL/SQL, Data Types, Error Codes

---

**Support & Feedback:**

For API issues:
- GitHub Issues: https://github.com/Haiwen-Yin/oracle-memory-system/issues
- API Team: api@oracle-memory.com

**Author:** 胖头鱼 🐟 (Haiwen Yin)

---

*This document is part of Oracle AI Database Memory System v1.0.0 Production Release*
