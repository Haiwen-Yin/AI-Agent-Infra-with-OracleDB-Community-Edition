# ⚡ Performance Optimization Guide

> **Complete performance optimization guide for Oracle AI Database Memory System v1.0.0**
> 
> **Version:** v1.0.0 Production Release  
> **Author:** 胖头鱼 🐟  
> **Last Updated:** 2024-12-19  
> **Status:** Production Ready ✅

## Table of Contents

1. [Performance Overview](#performance-overview)
2. [Vector Index Optimization](#vector-index-optimization)
3. [Query Optimization](#query-optimization)
4. [Connection Management](#connection-management)
5. [Batch Processing](#batch-processing)
6. [Memory Management](#memory-management)
7. [Caching Strategies](#caching-strategies)
8. [Monitoring and Diagnostics](#monitoring-and-diagnostics)
9. [Production Tuning](#production-tuning)
10. [Benchmarking](#benchmarking)

---

## Performance Overview

### Key Performance Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| Query Response Time | < 100ms | Vector similarity search latency |
| Throughput | > 1000 QPS | Queries per second |
| Index Build Time | < 5min | Time to create vector index |
| Memory Usage | < 8GB | Memory consumption per instance |
| CPU Usage | < 70% | CPU utilization during peak load |

### Performance Bottlenecks

**Common Issues:**

1. **Vector Index Missing** - Full table scans instead of index seek
2. **Inefficient Queries** - Poor SQL execution plans
3. **Connection Exhaustion** - Too many concurrent connections
4. **Memory Pressure** - Insufficient SGA/PGA allocation
5. **I/O Bottleneck** - Slow disk access for vector data

---

## Vector Index Optimization

### 1. HNSW Index Configuration

**Default Configuration:**

```sql
-- Create HNSW index (recommended for most use cases)
CREATE VECTOR INDEX idx_memories_embedding 
ON memories (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 16
  WITH TARGET ACCURACY 95
}
PARAMETERS (
  TYPE HNSW,
  MAX_SIMILARITY_SEARCH_RADIUS 0.8
);
```

**Optimized Configuration for Large Datasets:**

```sql
-- High-performance HNSW for 1M+ vectors
CREATE VECTOR INDEX idx_memories_embedding_hnsw 
ON memories (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 32
  WITH TARGET ACCURACY 98
}
PARAMETERS (
  TYPE HNSW,
  EF_SEARCH 128,
  EF_CONSTRUCTION 200,
  MAX_SIMILARITY_SEARCH_RADIUS 0.9
);

-- Set maintenance parameters
ALTER INDEX idx_memories_embedding_hnsw PARAMETERS (
  SET MAX_INDEX_SIZE 10GB,
  SET INDEX_BUILD_PARALLELISM 8
);
```

**Configuration Options:**

| Parameter | Default | Recommended | Description |
|-----------|---------|-------------|-------------|
| NEIGHBORS COUNT | 16 | 32-64 | Number of neighbors per node |
| EF_SEARCH | 64 | 128-256 | Search depth for queries |
| EF_CONSTRUCTION | 200 | 200-400 | Index build quality |
| TARGET ACCURACY | 95 | 98 | Accuracy percentage |

### 2. IVF Index Configuration

**For Write-Heavy Workloads:**

```sql
-- IVF index (better for frequent updates)
CREATE VECTOR INDEX idx_memories_embedding_ivf 
ON memories (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 100
  WITH TARGET ACCURACY 90
}
PARAMETERS (
  TYPE IVF,
  NUMBER_LISTS 1024,
  MAX_LIST_SIZE 1000
);

-- Rebuild periodically for optimal performance
ALTER INDEX idx_memories_embedding_ivf REBUILD;
```

**IVF vs HNSW Comparison:**

| Feature | HNSW | IVF |
|---------|------|-----|
| Query Speed | ⚡ Fast | 🐢 Slower |
| Build Time | 🐢 Slower | ⚡ Fast |
| Update Speed | 🐢 Slower | ⚡ Fast |
| Memory Usage | 🐢 Higher | ⚡ Lower |
| Use Case | Read-heavy | Write-heavy |

### 3. Index Maintenance

**Regular Maintenance Tasks:**

```sql
-- Monitor index health
SELECT 
  index_name,
  num_rows,
  leaf_blocks,
  clustering_factor
FROM user_indexes
WHERE index_name LIKE 'IDX_%EMBEDDING%';

-- Rebuild fragmented index
ALTER INDEX idx_memories_embedding REBUILD ONLINE;

-- Update index statistics
EXEC DBMS_STATS.GATHER_INDEX_STATS('OPENCLAW', 'IDX_MEMEMBEDDING');

-- Check index usage
SELECT 
  index_name,
  table_name,
  used,
  last_used
FROM user_objects_usage
WHERE object_name LIKE 'IDX_%EMBEDDING%';
```

### 4. Vector Dimension Optimization

**Dimension Reduction Techniques:**

```python
# Option 1: Use lower dimension model
# BGE-M3 (1024 dims) vs text-embedding-3-small (1536 dims)
embedding_model = "bge-m3"  # Better performance, smaller vectors

# Option 2: Apply dimension reduction
import numpy as np

def reduce_dimensions(vector, target_dims=512):
    """Apply PCA-like dimension reduction"""
    # Simple truncation (not recommended for production)
    return vector[:target_dims]
    
# Option 3: Quantization
def quantize_vector(vector, bits=8):
    """Reduce precision for storage efficiency"""
    scale = 2 ** bits - 1
    min_val = min(vector)
    max_val = max(vector)
    return [(v - min_val) / (max_val - min_val) * scale for v in vector]
```

---

## Query Optimization

### 1. Execution Plan Analysis

**Identify Slow Queries:**

```sql
-- Enable statistics gathering
ALTER SYSTEM SET STATISTICS_LEVEL = 'ALL';

-- Check execution plans
EXPLAIN PLAN FOR
SELECT memory_id, content, tags
FROM memories
WHERE memory_type = 'experience'
AND VECTOR_SIMILARITY(embedding_vector, 
    TO_VECTOR('[0.1, 0.2, 0.3, ...]', 1024, 32, 'FLOAT32'),
    'COSINE', 10) > 0.7;

SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY);

-- Identify full table scans
SELECT 
  operation,
  options,
  object_name,
  cost,
  cardinality
FROM PLAN_TABLE
WHERE operation = 'TABLE ACCESS'
AND options = 'FULL';
```

### 2. Query Rewrite Techniques

**Before Optimization:**

```sql
-- ❌ Bad: Full table scan with vector similarity
SELECT memory_id, content
FROM memories
WHERE VECTOR_SIMILARITY(embedding_vector, 
    TO_VECTOR('[0.1, 0.2, 0.3, ...]', 1024, 32, 'FLOAT32'),
    'COSINE', 100) > 0.7
AND memory_type = 'experience';
```

**After Optimization:**

```sql
-- ✅ Good: Use index hints and efficient filtering
SELECT /*+ INDEX(memories IDX_MEMEMBEDDING) */ 
  memory_id, content
FROM memories
WHERE memory_type = 'experience'  -- Filter first
AND VECTOR_SIMILARITY(embedding_vector, 
    TO_VECTOR('[0.1, 0.2, 0.3, ...]', 1024, 32, 'FLOAT32'),
    'COSINE', 10) > 0.7  -- Then vector search
FETCH FIRST 10 ROWS ONLY;
```

### 3. Partition Pruning

**Partition-Aware Queries:**

```sql
-- Use partition pruning
SELECT memory_id, content
FROM memories
WHERE partition_date >= TRUNC(SYSDATE) - 30  -- Prune old partitions
AND memory_type = 'experience'
AND VECTOR_SIMILARITY(embedding_vector, 
    TO_VECTOR('[0.1, 0.2, 0.3, ...]', 1024, 32, 'FLOAT32'),
    'COSINE', 10) > 0.7;

-- Verify partition pruning in execution plan
EXPLAIN PLAN FOR
SELECT * FROM memories
WHERE partition_date = TRUNC(SYSDATE);

SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY(format => 'PARTITION'));
```

### 4. Result Cache

**Enable Result Caching:**

```sql
-- Enable result cache for repeated queries
ALTER SYSTEM SET RESULT_CACHE_MODE = 'FORCE';

-- Query with result cache hint
SELECT /*+ RESULT_CACHE */ 
  memory_id, content, tags
FROM memories
WHERE memory_type = 'experience'
FETCH FIRST 10 ROWS ONLY;

-- Monitor cache usage
SELECT 
  name,
  count,
  bytes,
  hits
FROM V$RESULT_CACHE_STATISTICS;

SELECT 
  name,
  count,
  hash,
  invalidations
FROM V$RESULT_CACHE_OBJECTS
WHERE name LIKE '%MEMORIES%';
```

---

## Connection Management

### 1. Connection Pool Configuration

**Python Connection Pool:**

```python
import oracledb

# Initialize connection pool
pool = oracledb.create_pool(
    user="openclaw",
    password="hermes",
    dsn="10.10.10.130:1521/openclaw",
    min=5,           # Minimum connections
    max=20,          # Maximum connections
    increment=1,     # Increment size
    timeout=30,      # Connection timeout
    max_lifetime_session=1800,  # Max session lifetime
    session_callback=init_session
)

def init_session(connection, requestedTag):
    """Initialize session settings"""
    connection.autocommit = False
    connection.callTimeout = 30000  # 30 second timeout

# Use connection from pool
with pool.acquire() as connection:
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM memories WHERE ROWNUM = 1")
    result = cursor.fetchone()
```

**Connection Pool Monitoring:**

```sql
-- Monitor connection pool
SELECT 
  pool_name,
  status,
  open_servers,
  busy_servers,
  max_servers,
  session_idle_time
FROM V$CPOOL_STATS;

-- Monitor session activity
SELECT 
  username,
  status,
  machine,
  program,
  logon_time,
  last_call_et
FROM V$SESSION
WHERE username = 'OPENCLAW'
ORDER BY last_call_et DESC;

-- Kill idle sessions
ALTER SYSTEM KILL SESSION 'sid,serial#' IMMEDIATE;
```

### 2. Session Management

**Efficient Session Handling:**

```python
class SessionManager:
    def __init__(self, pool):
        self.pool = pool
        
    def get_session(self):
        """Get optimized session"""
        connection = self.pool.acquire()
        
        # Set session parameters
        cursor = connection.cursor()
        cursor.execute("""
            ALTER SESSION SET 
                OPTIMIZER_MODE = ALL_ROWS
                QUERY_REWRITE_ENABLED = TRUE
                STAR_TRANSFORMATION_ENABLED = TRUE
        """)
        
        return connection
        
    def release_session(self, connection):
        """Release session back to pool"""
        if connection:
            try:
                connection.rollback()  # Clean up any uncommitted work
            except:
                pass
            self.pool.release(connection)
```

### 3. Connection Scaling

**Auto-Scaling Configuration:**

```python
import threading
import time

class AutoScalingPool:
    def __init__(self, min_size=5, max_size=20, scale_threshold=0.8):
        self.min_size = min_size
        self.max_size = max_size
        self.scale_threshold = scale_threshold
        self.current_size = min_size
        self.lock = threading.Lock()
        
    def should_scale_up(self, active_connections):
        """Check if we need more connections"""
        return (active_connections / self.current_size) > self.scale_threshold
        
    def should_scale_down(self, active_connections):
        """Check if we can reduce connections"""
        return (active_connections / self.current_size) < 0.3
        
    def scale_up(self):
        """Increase pool size"""
        with self.lock:
            if self.current_size < self.max_size:
                self.current_size = min(self.current_size + 2, self.max_size)
                return True
        return False
        
    def scale_down(self):
        """Decrease pool size"""
        with self.lock:
            if self.current_size > self.min_size:
                self.current_size = max(self.current_size - 1, self.min_size)
                return True
        return False
```

---

## Batch Processing

### 1. Bulk Insert Optimization

**Fast Bulk Insert:**

```python
def bulk_insert_memories(connection, memories_data, batch_size=1000):
    """Efficient bulk insert using executemany"""
    cursor = connection.cursor()
    
    # Prepare statement
    insert_sql = """
        INSERT INTO memories (content, memory_type, tags, metadata, embedding_vector)
        VALUES (:1, :2, :3, :4, TO_VECTOR(:5, 1024, 32, 'FLOAT32'))
    """
    
    # Process in batches
    for i in range(0, len(memories_data), batch_size):
        batch = memories_data[i:i + batch_size]
        
        # Execute batch insert
        cursor.executemany(insert_sql, [
            (m['content'], m['memory_type'], m['tags'], 
             m['metadata'], m['embedding_vector'])
            for m in batch
        ])
        
        connection.commit()
        print(f"Inserted batch {i // batch_size + 1}")
    
    return cursor.rowcount
```

**SQL Bulk Insert:**

```sql
-- Enable direct-path insert
ALTER SESSION ENABLE DIRECT PATH INSERT;

-- Bulk insert using APPEND hint
INSERT /*+ APPEND */ INTO memories
SELECT 
  memory_id_seq.NEXTVAL,
  content,
  memory_type,
  tags,
  metadata,
  embedding_vector
FROM memories_staging
WHERE processed = 'N';

-- Commit in batches
COMMIT;

-- Disable direct-path insert
ALTER SESSION DISABLE DIRECT PATH INSERT;
```

### 2. Batch Vector Generation

**Parallel Embedding Generation:**

```python
import concurrent.futures
from multiprocessing import cpu_count

def generate_embeddings_parallel(texts, model, batch_size=100):
    """Generate embeddings in parallel"""
    
    def process_batch(batch):
        return model.encode(batch)
    
    # Split into batches
    batches = [texts[i:i + batch_size] 
               for i in range(0, len(texts), batch_size)]
    
    # Process in parallel
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=cpu_count()
    ) as executor:
        results = list(executor.map(process_batch, batches))
    
    # Flatten results
    return [embedding for batch in results for embedding in batch]
```

### 3. Batch Processing Pipeline

**Production Pipeline:**

```python
class BatchProcessor:
    def __init__(self, connection, batch_size=1000):
        self.connection = connection
        self.batch_size = batch_size
        
    def process_memories(self, query):
        """Process memories in batches"""
        cursor = self.connection.cursor()
        
        # Execute query
        cursor.execute(query)
        
        batch = []
        processed = 0
        
        while True:
            row = cursor.fetchone()
            if row is None:
                break
                
            batch.append(row)
            
            if len(batch) >= self.batch_size:
                self._process_batch(batch)
                processed += len(batch)
                print(f"Processed {processed} memories")
                batch = []
        
        # Process remaining
        if batch:
            self._process_batch(batch)
            processed += len(batch)
            
        return processed
        
    def _process_batch(self, batch):
        """Process a single batch"""
        # Implementation depends on specific use case
        pass
```

---

## Memory Management

### 1. SGA Optimization

**Shared Pool Tuning:**

```sql
-- Check shared pool usage
SELECT 
  name,
  value,
  bytes
FROM V$PARAMETER
WHERE name IN ('shared_pool_size', 'large_pool_size', 'java_pool_size');

-- Monitor shared pool
SELECT 
  name,
  bytes/1024/1024 AS size_mb
FROM V$SGASTAT
WHERE pool = 'shared pool'
AND name IN ('library cache', 'dictionary cache', 'free memory');

-- Resize shared pool
ALTER SYSTEM SET shared_pool_size = 4G SCOPE = BOTH;

-- Check library cache hit ratio
SELECT 
  SUM(pins) AS total_pins,
  SUM(reloads) AS total_reloads,
  (SUM(pins) - SUM(reloads)) / SUM(pins) * 100 AS hit_ratio
FROM V$LIBRARYCACHE;
```

**Buffer Cache Tuning:**

```sql
-- Check buffer cache hit ratio
SELECT 
  name,
  value
FROM V$SYSSTAT
WHERE name IN ('db block gets', 'consistent gets', 'physical reads');

-- Calculate hit ratio
SELECT 
  (1 - (phy.r / (cur.r + db.r))) * 100 AS hit_ratio
FROM 
  (SELECT value AS r FROM V$SYSSTAT WHERE name = 'physical reads') phy,
  (SELECT value AS r FROM V$SYSSTAT WHERE name = 'consistent gets') cur,
  (SELECT value AS r FROM V$SYSSTAT WHERE name = 'db block gets') db;

-- Resize buffer cache
ALTER SYSTEM SET db_cache_size = 8G SCOPE = BOTH;
```

### 2. PGA Optimization

**Sort and Hash Operations:**

```sql
-- Check PGA usage
SELECT 
  name,
  value,
  100 * value / (SELECT value FROM V$PGASTAT WHERE name = 'maximum PGA allocated') AS pct
FROM V$PGASTAT
WHERE name IN ('total PGA allocated', 'total PGA inuse', 'maximum PGA allocated');

-- Monitor sort operations
SELECT 
  name,
  value
FROM V$SYSSTAT
WHERE name LIKE 'sort%';

-- Optimize PGA
ALTER SYSTEM SET pga_aggregate_target = 4G SCOPE = BOTH;
ALTER SYSTEM SET pga_aggregate_limit = 8G SCOPE = BOTH;
```

### 3. Memory Monitoring Script

**Python Memory Monitor:**

```python
import psutil
import time
from datetime import datetime

class MemoryMonitor:
    def __init__(self, warning_threshold=80, critical_threshold=90):
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        
    def check_memory(self):
        """Check system memory usage"""
        memory = psutil.virtual_memory()
        
        return {
            'total': memory.total,
            'available': memory.available,
            'used': memory.used,
            'percent': memory.percent,
            'timestamp': datetime.now()
        }
        
    def monitor_loop(self, interval=60):
        """Continuous memory monitoring"""
        while True:
            mem_info = self.check_memory()
            
            if mem_info['percent'] > self.critical_threshold:
                print(f"CRITICAL: Memory usage at {mem_info['percent']}%")
                self._send_alert('CRITICAL', mem_info)
            elif mem_info['percent'] > self.warning_threshold:
                print(f"WARNING: Memory usage at {mem_info['percent']}%")
                self._send_alert('WARNING', mem_info)
                
            time.sleep(interval)
            
    def _send_alert(self, level, mem_info):
        """Send memory alert"""
        # Implement alerting logic
        pass
```

---

## Caching Strategies

### 1. In-Memory Cache

**LRU Cache Implementation:**

```python
from functools import lru_cache
import hashlib

class VectorCache:
    def __init__(self, max_size=1000, ttl=300):
        self.max_size = max_size
        self.ttl = ttl
        self.cache = {}
        self.access_times = {}
        
    def _make_key(self, query_vector, memory_type):
        """Generate cache key"""
        key_data = f"{query_vector.tobytes()}_{memory_type}"
        return hashlib.md5(key_data.encode()).hexdigest()
        
    def get(self, query_vector, memory_type):
        """Get cached result"""
        key = self._make_key(query_vector, memory_type)
        
        if key in self.cache:
            # Check TTL
            if time.time() - self.access_times[key] < self.ttl:
                return self.cache[key]
            else:
                # Expired
                del self.cache[key]
                del self.access_times[key]
                
        return None
        
    def set(self, query_vector, memory_type, results):
        """Cache results"""
        key = self._make_key(query_vector, memory_type)
        
        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.access_times, key=self.access_times.get)
            del self.cache[oldest_key]
            del self.access_times[oldest_key]
            
        self.cache[key] = results
        self.access_times[key] = time.time()
        
    def clear(self):
        """Clear cache"""
        self.cache.clear()
        self.access_times.clear()
```

### 2. Redis Cache Integration

**Redis Setup:**

```python
import redis
import json

class RedisVectorCache:
    def __init__(self, host='localhost', port=6379, db=0):
        self.redis = redis.Redis(host=host, port=port, db=db)
        self.default_ttl = 300
        
    def get_cached_results(self, query_hash):
        """Get cached vector search results"""
        cached = self.redis.get(f"vector:{query_hash}")
        
        if cached:
            return json.loads(cached)
        return None
        
    def set_cached_results(self, query_hash, results, ttl=None):
        """Cache vector search results"""
        ttl = ttl or self.default_ttl
        
        self.redis.setex(
            f"vector:{query_hash}",
            ttl,
            json.dumps(results)
        )
        
    def invalidate_pattern(self, pattern):
        """Invalidate cache by pattern"""
        keys = self.redis.keys(f"vector:{pattern}")
        if keys:
            self.redis.delete(*keys)
```

### 3. Application-Level Cache

**Multi-Level Cache:**

```python
class MultiLevelCache:
    def __init__(self):
        self.l1_cache = {}  # In-memory (fast, small)
        self.l2_cache = {}  # Local disk (slower, larger)
        self.l3_cache = None  # Redis (shared, largest)
        
    def get(self, key):
        """Get from cache hierarchy"""
        # L1: Memory
        if key in self.l1_cache:
            return self.l1_cache[key]
            
        # L2: Disk
        if key in self.l2_cache:
            value = self._load_from_disk(key)
            self.l1_cache[key] = value
            return value
            
        # L3: Redis
        if self.l3_cache:
            value = self.l3_cache.get(key)
            if value:
                self.l1_cache[key] = value
                return value
                
        return None
        
    def set(self, key, value, levels=None):
        """Set in specified cache levels"""
        levels = levels or ['l1', 'l2', 'l3']
        
        if 'l1' in levels:
            self.l1_cache[key] = value
            
        if 'l2' in levels:
            self._save_to_disk(key, value)
            
        if 'l3' in levels and self.l3_cache:
            self.l3_cache.set(key, value)
```

---

## Monitoring and Diagnostics

### 1. Performance Monitoring

**Oracle Performance Views:**

```sql
-- Top SQL by elapsed time
SELECT 
  sql_id,
  sql_text,
  elapsed_time/1000000 AS elapsed_sec,
  cpu_time/1000000 AS cpu_sec,
  buffer_gets,
  disk_reads,
  executions
FROM V$SQL
WHERE elapsed_time > 0
ORDER BY elapsed_time DESC
FETCH FIRST 20 ROWS ONLY;

-- Active sessions
SELECT 
  s.sid,
  s.serial#,
  s.username,
  s.program,
  s.machine,
  s.sql_id,
  s.event,
  s.wait_class,
  s.seconds_in_wait
FROM V$SESSION s
WHERE s.status = 'ACTIVE'
AND s.type = 'USER'
ORDER BY s.seconds_in_wait DESC;

-- I/O statistics
SELECT 
  filename,
  phyrds AS physical_reads,
  phywrts AS physical_writes,
  readtim AS read_time,
  writetim AS write_time
FROM V$FILESTAT
ORDER BY phyyrds DESC;
```

### 2. Vector-Specific Monitoring

**Vector Index Monitoring:**

```sql
-- Monitor vector index usage
SELECT 
  index_name,
  num_rows,
  leaf_blocks,
  clustering_factor,
  last_analyzed
FROM USER_INDEXES
WHERE index_name LIKE '%EMBEDDING%';

-- Vector search performance
SELECT 
  sql_id,
  sql_text,
  elapsed_time/1000000 AS elapsed_sec,
  buffer_gets
FROM V$SQL
WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
ORDER BY elapsed_time DESC;

-- Vector memory usage
SELECT 
  name,
  value/1024/1024 AS size_mb
FROM V$PARAMETER
WHERE name LIKE '%vector%';
```

### 3. Automated Monitoring Script

**Python Monitoring:**

```python
import time
import logging
from datetime import datetime

class PerformanceMonitor:
    def __init__(self, connection, log_file='performance.log'):
        self.connection = connection
        self.logger = self._setup_logger(log_file)
        
    def _setup_logger(self, log_file):
        """Setup logging"""
        logger = logging.getLogger('PerformanceMonitor')
        logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler(log_file)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
        
    def monitor_sql_performance(self):
        """Monitor SQL performance"""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT 
              sql_id,
              sql_text,
              elapsed_time/1000000 AS elapsed_sec,
              buffer_gets
            FROM V$SQL
            WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
            AND elapsed_time > 1000000  -- > 1 second
            ORDER BY elapsed_time DESC
            FETCH FIRST 10 ROWS ONLY
        """)
        
        results = cursor.fetchall()
        
        for row in results:
            self.logger.warning(
                f"Slow query detected: {row[0]} - {row[2]:.2f}s"
            )
            
        return results
        
    def monitor_connections(self):
        """Monitor connection usage"""
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT 
              COUNT(*) AS total,
              SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END) AS active,
              SUM(CASE WHEN status = 'INACTIVE' THEN 1 ELSE 0 END) AS inactive
            FROM V$SESSION
            WHERE username = 'OPENCLAW'
        """)
        
        result = cursor.fetchone()
        
        if result[1] > 50:  # More than 50 active sessions
            self.logger.warning(
                f"High connection usage: {result[1]} active sessions"
            )
            
        return result
        
    def generate_report(self):
        """Generate performance report"""
        report = {
            'timestamp': datetime.now(),
            'sql_performance': self.monitor_sql_performance(),
            'connections': self.monitor_connections()
        }
        
        return report
```

---

## Production Tuning

### 1. Database Parameter Tuning

**Key Parameters:**

```sql
-- Memory Parameters
ALTER SYSTEM SET sga_target = 16G SCOPE = BOTH;
ALTER SYSTEM SET sga_max_size = 32G SCOPE = SPFILE;
ALTER SYSTEM SETpga_aggregate_target = 8G SCOPE = BOTH;

-- I/O Parameters
ALTER SYSTEM SET db_file_multiblock_read_count = 16 SCOPE = BOTH;
ALTER SYSTEM SET disk_asynch_io = TRUE SCOPE = BOTH;

-- Parallel Execution
ALTER SYSTEM SET parallel_max_servers = 64 SCOPE = BOTH;
ALTER SYSTEM SET parallel_min_servers = 8 SCOPE = BOTH;

-- Query Optimization
ALTER SYSTEM SET optimizer_adaptive_plans = TRUE SCOPE = BOTH;
ALTER SYSTEM SET optimizer_adaptive_statistics = TRUE SCOPE = BOTH;

-- Vector Operations
ALTER SYSTEM SET vector_memory_size = 2G SCOPE = BOTH;
```

### 2. SQL Profile Tuning

**Create SQL Profile:**

```sql
-- Create SQL profile for vector queries
DECLARE
  profile_name VARCHAR2(30) := 'VECTOR_SEARCH_PROFILE';
BEGIN
  DBMS_SQLTUNE.CREATE_SQL_PROFILE(
    profile_name => profile_name,
    category => 'DEFAULT',
    sql_text => 'SELECT /*+ INDEX(memories IDX_MEMEMBEDDING) */ ...',
    profile_type => DBMS_SQLTUNE.PROFILE_TYPE_SQL_PROFILE
  );
  
  -- Apply profile hints
  DBMS_SQLTUNE.ALTER_SQL_PROFILE(
    profile_name => profile_name,
    attribute_name => 'FORCE_MATCH',
    value => 'YES'
  );
END;
```

### 3. Resource Management

**Resource Plan:**

```sql
-- Create consumer group
BEGIN
  DBMS_RESOURCE_MANAGER.CREATE_CONSUMER_GROUP(
    consumer_group => 'VECTOR_SEARCH_GROUP',
    comment => 'Group for vector search operations'
  );
END;

-- Create resource plan
BEGIN
  DBMS_RESOURCE_MANAGER.CREATE_PLAN(
    plan => 'VECTOR_SEARCH_PLAN',
    comment => 'Plan for vector search workloads'
  );
END;

-- Create resource plan directive
BEGIN
  DBMS_RESOURCE_MANAGER.CREATE_PLAN_DIRECTIVE(
    plan => 'VECTOR_SEARCH_PLAN',
    group_or_subplan => 'VECTOR_SEARCH_GROUP',
    max_utilization_limit => 50,
    mgmt_p6 => 100
  );
END;
```

---

## Benchmarking

### 1. Vector Search Benchmark

**Benchmark Script:**

```python
import time
import statistics
from concurrent.futures import ThreadPoolExecutor

class VectorBenchmark:
    def __init__(self, system):
        self.system = system
        
    def benchmark_search(self, query_vectors, iterations=100):
        """Benchmark vector search performance"""
        latencies = []
        
        for i in range(iterations):
            query_vector = query_vectors[i % len(query_vectors)]
            
            start_time = time.time()
            results = self.system.search_similar_memories(
                query_vector=query_vector,
                limit=10
            )
            end_time = time.time()
            
            latencies.append((end_time - start_time) * 1000)  # ms
            
        return {
            'avg_latency_ms': statistics.mean(latencies),
            'median_latency_ms': statistics.median(latencies),
            'p95_latency_ms': sorted(latencies)[int(len(latencies) * 0.95)],
            'p99_latency_ms': sorted(latencies)[int(len(latencies) * 0.99)],
            'min_latency_ms': min(latencies),
            'max_latency_ms': max(latencies)
        }
        
    def benchmark_concurrent_search(self, query_vectors, concurrency=10):
        """Benchmark concurrent search performance"""
        latencies = []
        
        def search_task(query_vector):
            start_time = time.time()
            results = self.system.search_similar_memories(
                query_vector=query_vector,
                limit=10
            )
            end_time = time.time()
            return (end_time - start_time) * 1000
            
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(search_task, qv)
                for qv in query_vectors[:concurrency]
            ]
            
            for future in futures:
                latencies.append(future.result())
                
        return {
            'concurrency': concurrency,
            'avg_latency_ms': statistics.mean(latencies),
            'throughput_qps': concurrency / (statistics.mean(latencies) / 1000)
        }
```

### 2. Load Testing

**Load Test Script:**

```python
class LoadTest:
    def __init__(self, system, duration_seconds=300):
        self.system = system
        self.duration = duration_seconds
        
    def run_load_test(self, target_qps=100):
        """Run load test"""
        start_time = time.time()
        results = {
            'successful': 0,
            'failed': 0,
            'latencies': []
        }
        
        while time.time() - start_time < self.duration:
            # Execute search
            try:
                search_start = time.time()
                self.system.search_similar_memories(
                    query_vector=self._random_vector(),
                    limit=10
                )
                latency = (time.time() - search_start) * 1000
                
                results['successful'] += 1
                results['latencies'].append(latency)
            except Exception as e:
                results['failed'] += 1
                
            # Control QPS
            time.sleep(1 / target_qps)
            
        return self._calculate_statistics(results)
        
    def _random_vector(self):
        """Generate random vector for testing"""
        import random
        return [random.random() for _ in range(1024)]
        
    def _calculate_statistics(self, results):
        """Calculate test statistics"""
        return {
            'duration_seconds': self.duration,
            'total_requests': results['successful'] + results['failed'],
            'successful_requests': results['successful'],
            'failed_requests': results['failed'],
            'success_rate': results['successful'] / (results['successful'] + results['failed']),
            'avg_latency_ms': statistics.mean(results['latencies']) if results['latencies'] else 0,
            'p95_latency_ms': sorted(results['latencies'])[int(len(results['latencies']) * 0.95)] if results['latencies'] else 0,
            'throughput_qps': results['successful'] / self.duration
        }
```

---

## Conclusion

This performance optimization guide covers:

1. **Vector Index Optimization** - HNSW/IVF configuration and maintenance
2. **Query Optimization** - Execution plan analysis and query rewriting
3. **Connection Management** - Pool configuration and session optimization
4. **Batch Processing** - Bulk operations and parallel execution
5. **Memory Management** - SGA/PGA tuning and monitoring
6. **Caching Strategies** - Multi-level cache implementation
7. **Monitoring** - Performance tracking and diagnostics
8. **Production Tuning** - Database parameters and resource management
9. **Benchmarking** - Performance measurement and load testing

**Key Recommendations:**

- Start with HNSW index for most use cases
- Monitor vector search latency regularly
- Use connection pooling in production
- Implement batch processing for bulk operations
- Enable result caching for repeated queries
- Set up automated monitoring and alerting
- Run regular performance benchmarks

---

**Version History:**

- v1.0.0 (2024-12-19): Initial performance optimization guide
- Includes: Vector optimization, query tuning, monitoring, benchmarking

---

**Support & Feedback:**

For performance issues:
- GitHub Issues: https://github.com/Haiwen-Yin/oracle-memory-system/issues
- Performance Team: performance@oracle-memory.com

**Author:** 胖头鱼 🐟 (Haiwen Yin)

---

*This document is part of Oracle AI Database Memory System v1.0.0 Production Release*
