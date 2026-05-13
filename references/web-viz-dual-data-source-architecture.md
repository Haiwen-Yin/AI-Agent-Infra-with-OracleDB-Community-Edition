# Web Visualization Server — Dual Data Source Architecture

## Problem
User requested Knowledge and Memory pages show DIFFERENT content. Initially implemented as filtering same data by node type, but database has no `MEMORY` type nodes — both pages showed identical data.

## Solution
Two completely independent data pipelines:

### Knowledge Graph Pipeline
```
KNOWLEDGE_CONCEPTS table → load_knowledge_data() → _knowledge_cache → /api/knowledge
KNOWLEDGE_GRAPH table    ↗
```

### Memory Pipeline
```
MEMORY_NODES table  → load_memory_data() → _memory_cache → /api/memory
MEMORY_EDGES table  ↗
```

## Key Implementation Details

### Separate Cache Objects
```python
_knowledge_cache = {'data': None, 'timestamp': None, 'ttl': 300}
_memory_cache = {'data': None, 'timestamp': None, 'ttl': 300}
```

### API Endpoint Selection in JavaScript
```javascript
const apiUrl = mode === 'memory' ? '/api/memory' : '/api/knowledge';
fetch(apiUrl).then(r => r.json()).then(data => { ... });
```

### Independent Invalidation
```python
# Refresh knowledge only
elif path == '/api/knowledge/refresh':
    with _cache_lock:
        _knowledge_cache['data'] = None
        _knowledge_cache['timestamp'] = None
    self.send_graph_data('knowledge')
```

## Data Counts (as of 2026-05-12)
- Knowledge: 44 nodes, 40 edges (from KNOWLEDGE_CONCEPTS + KNOWLEDGE_GRAPH)
- Memory: 41 nodes, 23 edges (from MEMORY_NODES + MEMORY_EDGES)

## Pitfall: Route Renaming
When renaming routes (e.g., `/graph` → `/knowledge`), ALL references must be updated:
1. `do_GET` route matching
2. `do_POST` login redirect (`Location: /knowledge`)
3. HTML template onclick handlers (`window.location.href = '/knowledge'`)
4. JavaScript `fetch()` calls
5. Login page redirect after successful auth

Missing ANY ONE causes silent 404s or wrong-page loads.
