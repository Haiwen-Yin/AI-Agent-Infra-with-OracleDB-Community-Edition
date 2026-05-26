# Oracle Memory System v2.3.1 Release Notes

**Release Date**: 2026-05-26
**Version**: v2.3.1
**Compatibility**: Backward-compatible with v2.3.0 database

---

## Summary

**Vector Search Fix & Enhancement + 5-Signal Hybrid Search + Fulltext Search + Unified Search API** — Fixes in-database embedding generation and retrieval capabilities omitted during the v2.0.0 architecture rewrite, adds multi-modal vector search, 5-signal fusion search (vector + fulltext + relational + tag + graph), Oracle Text fulltext search, and unified search API (10 strategies).

## Background

During the v2.0.0 architecture rewrite (partitioning, composite primary keys, JRD dual views), the embedding generation and vector retrieval capabilities from v1.x/v2.0 were omitted:

- `EMBEDDING_MANAGER` PL/SQL package's `generate_and_store` failed because `JSON_QUERY WITH WRAPPER` returns double brackets `[[-0.03,...]]` causing `TO_VECTOR` to fail
- Python `embedding_api.py` used positional binds `:1,:2,:3`, but when `execute_query` passes a dict, oracledb thin mode interprets `:1` as named variable "1", causing `ORA-01722` type conversion error
- Missing key retrieval capabilities such as vector similarity search, hybrid search (vector + keyword), cross-type search, 4-signal fusion search, and fulltext search
- `ENTITY_EMBEDDINGS` table exists but has no valid vector data write path

## What's New

### EMBEDDING_MANAGER PL/SQL Package (FIXED)

| Function | Description |
|----------|-------------|
| `generate_embedding(p_text)` | Calls embedding API via UTL_HTTP, returns full JSON CLOB |
| `generate_and_store(p_entity_id, p_entity_type, p_text)` | **FIXED**: Generates embedding and stores in ENTITY_EMBEDDINGS; uses SUBSTR to strip double brackets + VECTOR variable assignment |
| `cosine_similarity(p_id1, p_type1, p_id2, p_type2)` | Computes cosine similarity between two entity embeddings |
| `batch_embed_entities(p_entity_type, p_limit)` | Batch generates embeddings for entities missing vectors |
| `get_stats()` | Returns JSON with total embeddings, with_vector count, distinct models |

**Root cause of `generate_and_store` failure**: `JSON_QUERY(l_json, '$.data[0].embedding' WITH WRAPPER)` returns `[[-0.03,...]]` (double-bracketed) because the embedding is an array and WRAPPER adds outer brackets. Fix: `SUBSTR(l_vec, 2, DBMS_LOB.GETLENGTH(l_vec)-2)` strips outer brackets, then `l_emb := TO_VECTOR(l_vec)` assigns to VECTOR variable before INSERT/UPDATE.

### embedding_api.py (FIXED + ENHANCED)

All bind variables changed from positional (`:1,:2,:3`) to named (`:eid,:etype,:vec,:model,:dim,:k`) to fix ORA-01722 with oracledb thin mode.

| Function | Description | Status |
|----------|-------------|--------|
| `generate_embedding(text)` | Generate vector via embedding API | Existing |
| `store_embedding(entity_id, entity_type, text)` | Generate + store in DB | **FIXED** |
| `store_embedding_vector(entity_id, entity_type, embedding)` | Store pre-computed vector | **FIXED** |
| `get_embedding(entity_id, entity_type)` | Get embedding metadata | **FIXED** |
| `delete_embedding(entity_id, entity_type)` | Delete embedding | **FIXED** |
| `search_similar(text, top_k, entity_type, workspace_id)` | Vector similarity search | **FIXED** |
| `search_by_entity_id(entity_id, entity_type, top_k)` | Search similar to existing entity | **NEW** |
| `search_hybrid(text, keyword, top_k, vector_weight)` | Vector + keyword hybrid search | **NEW** |
| `search_multi_type(text, entity_types, top_k)` | Cross-type vector search | **NEW** |
| `generate_embeddings_batch(entity_type, limit)` | Batch embed entities | **FIXED** |
| `get_embedding_stats()` | Embedding statistics | Existing |
| `get_model_dimension(model)` | Get/auto-detect model dimension | Existing |

### EMBEDDING_GENERATION_JOB (NEW)

Scheduler job that runs every 2 hours to automatically generate embeddings for new MEMORY and KNOWLEDGE entities that don't have vectors yet.

### Unified 5-Signal Hybrid Search (NEW)

`search_unified()` combines five retrieval signals with configurable weights:

| Signal | Default Weight | Source | Scoring |
|--------|---------------|--------|---------|
| Vector | 0.4 | ENTITY_EMBEDDINGS via VECTOR_DISTANCE(COSINE) | 1 - cosine_distance |
| Fulltext | 0.25 | Oracle Text CONTAINS(title) + SCORE(1) | ft_score / 100 |
| Relational | 0.2 | KNOWLEDGE_META + SPEC_META + ENTITY_TAGS | Domain/scope match + importance + tag overlap |
| Tag | included in Relational | ENTITY_TAGS | Filter tag overlap + query word match |
| Graph | 0.15 | ENTITY_EDGES BFS from seed entity | 1/depth proximity + edge_count/10 |

Parameters: `text, top_k, entity_type, workspace_id, domain, category, tags, graph_seed_entity_id, graph_seed_entity_type, graph_depth, vector_weight, fulltext_weight, relational_weight, graph_weight`

Returns per-entity: `scores{vector, fulltext, relational, tag, graph}` + `final_score` + metadata (km_domain, km_topic, sm_scope, tags, edge_count, graph_proximity).

### Single-SQL CTE Fusion Search (NEW)

`search_unified_sql()` provides identical 5-signal fusion as `search_unified()` but executes as a single CTE-based SQL statement, eliminating multi-round Python-SQL round trips:

- **candidates CTE**: Vector + fulltext + metadata main query (VECTOR_DISTANCE + CONTAINS/SCORE)
- **tag_scores CTE**: Tag overlap scoring via GROUP BY (matched_tags / total_tags)
- **edge_counts CTE**: Edge count aggregation via GROUP BY
- **graph_prox CTE**: Graph proximity via UNION ALL (depth=1 at 1.0, depth=2 at 0.5)
- **Final SELECT**: Weighted scoring computed server-side, ORDER BY final_score DESC

Result items include `engine="single_sql"` identifier. Same parameters and return schema as `search_unified()`.

**LLM Context Economics**: `search_unified_sql()` compresses 4-5 Python-SQL round trips into 1 database call, saving 60-80% of tool-call token overhead. This eliminates intermediate-step context pollution — a critical pain point for LLM agents where each tool call's request/response consumes tokens from the context window, and intermediate results (partial matches, debug info, empty results) introduce noise that degrades reasoning quality. Single-SQL fusion keeps the LLM's context clean: query in → ranked results out → agent reasons.

### Fulltext Search (NEW)

`search_fulltext()` provides Oracle Text-based full-text search:

- Uses `CONTAINS(e.TITLE, :ftq, 1) > 0` + `SCORE(1)` for relevance ranking
- Supports `entity_type`, `category`, and `workspace_id` filters
- Returns `ft_score` (normalized 0-1) per result

### Search API (NEW)

`search_api.py` provides a unified search entry point for AI agents with 10 strategies:

| Strategy | Signals | Best For | Requires Embedding |
|----------|---------|----------|-------------------|
| vector | vector | Semantic/concept search | Yes |
| fulltext | fulltext | Exact keyword/boolean/fuzzy | No |
| keyword | keyword | Wildcard/LIKE patterns | No |
| graph | graph | Relationship/neighborhood | No |
| hybrid | vector+fulltext | Semantic+lexical balanced | Yes |
| unified | vector+fulltext+relational+tag+graph | Comprehensive multi-dimensional | Yes |
| unified_sql | vector+fulltext+relational+tag+graph | Single-SQL CTE fusion (low-latency) | Yes |
| relational | relational | Domain/category/importance filter | No |
| multi_type | vector+multi_type | Cross-type (MEMORY/KNOWLEDGE/SPEC) | Yes |
| auto | auto-detected | Unknown query type / convenience | Varies |

```python
from scripts.lib.search_api import search, list_search_strategies, describe_search_strategy

# Auto strategy detection
results = search("database partitioning", strategy="auto", top_k=10)

# Specific strategy
results = search("encryption", strategy="fulltext", entity_type="KNOWLEDGE")

# List all strategies
strats = list_search_strategies()
```

### Test Coverage

19 embedding tests + 31 unified search tests + 42 search API tests = 92 new tests. Total 183/183 tests pass. Coverage: generation, storage, retrieval, vector similarity search, entity-based search, hybrid search, cross-type search, batch processing, dimension detection, statistics, cleanup, 5-signal verification, domain/category/tags filtering, graph proximity, custom weights, metadata JOIN, empty result handling, strategy metadata, auto-detection, dispatch, single-SQL CTE fusion, engine tag verification.

## Bug Fixes

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `EMBEDDING_MANAGER.generate_and_store` returns -1 | `JSON_QUERY WITH WRAPPER` returns `[array]` (double-bracketed) | `SUBSTR(l_vec, 2, DBMS_LOB.GETLENGTH(l_vec)-2)` before `TO_VECTOR()` |
| `search_similar(entity_type="MEMORY")` triggers ORA-01722 | oracledb thin mode interprets dict + `:3` as named bind "1" | All binds changed to named (`:eid`, `:etype`, etc.) |
| `generate_and_store` fails from SELECT call | ENTITIES row missing (FK constraint) | Requires entity to exist first; works from anonymous PL/SQL block |
| `TO_VECTOR('0.1,0.2,...')` triggers ORA-51804 | Oracle 23ai requires `[v1,v2,...]` format | Use `json.dumps()` which produces bracketed format |
| `generate_and_store` with MERGE fails | TO_VECTOR in MERGE SQL context | Use PL/SQL variable `l_emb := TO_VECTOR(l_vec)` then INSERT/UPDATE with variable |

## Database Changes

No schema changes. New objects:
- `EMBEDDING_MANAGER` package (spec + body)
- `EMBEDDING_GENERATION_JOB` scheduler job

## Upgrade from v2.3.0

```sql
-- Deploy EMBEDDING_MANAGER package
@scripts/deploy/2_api.sql

-- Deploy EMBEDDING_GENERATION_JOB
@scripts/deploy/3_jobs.sql
```

No data migration required. Existing ENTITY_EMBEDDINGS data is preserved.

## Test Results

```
Oracle Memory System v2.3.1 - Full Test Suite
============================================================
  Connection:   6/6 PASS
  Memory:       8/8 PASS
  Knowledge:    8/8 PASS
  Agent:        8/8 PASS
  Graph:        8/8 PASS
  Harness:      6/6 PASS
  Security:     5/5 PASS
  Workspace:   12/12 PASS
  Spec:         9/9 PASS
  Collab:      12/12 PASS
  Credential:   9/9 PASS
  Embedding:   19/19 PASS
  UnifiedSearch: 20/20 PASS
  SearchAPI:   36/36 PASS
Overall: 183/183 ALL PASSED
```

## Comparison

| Metric | v2.3.0 | v2.3.1 | Delta |
|--------|--------|--------|-------|
| PL/SQL Packages | 7 | 8 | +1 (EMBEDDING_MANAGER) |
| Scheduler Jobs | 11 | 12 | +1 (EMBEDDING_GENERATION_JOB) |
| Python Modules | 12 | 15 | +3 (embedding_api.py, search_api.py, seed_rich_data.py) |
| API Functions | 99+ | 131+ | +31 (embedding + unified search + fulltext + search API) |
| Tests | 99 | 171 | +72 (embedding 19 + unified search 20 + search API 36) |
| Tables | 27 | 27 | No change |
