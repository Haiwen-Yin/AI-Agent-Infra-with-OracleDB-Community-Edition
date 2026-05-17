# Performance Optimization Quick Reference

> Condensed reference for Oracle Memory System v1.0.0 performance tuning.

## Vector Index Selection

| Workload | Index Type | Key Parameters |
|----------|-----------|----------------|
| Read-heavy (default) | HNSW | NEIGHBORS=32, EF_SEARCH=128, EF_CONSTRUCTION=200 |
| Write-heavy | IVF | NUMBER_LISTS=1024, MAX_LIST_SIZE=1000 |
| Large datasets (>1M) | IVF | NUMBER_LISTS=4096, MAX_LIST_SIZE=2000 |

## Query Optimization Checklist

1. Use `/*+ INDEX(table IDX_EMBEDDING_HNSW) */` hint for vector searches
2. Filter with WHERE clause BEFORE vector similarity (reduce candidate set)
3. Use `FETCH FIRST N ROWS ONLY` instead of large LIMIT
4. Enable partition pruning with date range filters
5. Use RESULT_CACHE hint for repeated queries

## Connection Pool Tuning

- Min connections: 5 (baseline)
- Max connections: 20 (adjust based on concurrent users)
- Connection timeout: 30s
- Max session lifetime: 1800s (30min)

## Key Monitoring Queries

```sql
-- Slow vector queries
SELECT sql_id, elapsed_time/1000000 AS sec, buffer_gets
FROM V$SQL WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
ORDER BY elapsed_time DESC FETCH FIRST 10 ROWS ONLY;

-- Index health
SELECT index_name, clustering_factor, num_rows,
  CASE WHEN clustering_factor < num_rows * 0.1 THEN 'GOOD' ELSE 'NEEDS REBUILD' END AS health
FROM user_indexes WHERE index_name LIKE 'IDX_%EMBEDDING%';
```
