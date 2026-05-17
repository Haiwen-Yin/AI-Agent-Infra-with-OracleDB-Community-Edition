# Web Visualization Dual-Page Architecture

**Author**: Haiwen Yin (胖头鱼 🐟)
**Date**: 2026-05-12
**Version**: v1.4.0

## Overview

v1.4.0 introduces dual-page visualization architecture that separates Knowledge Graph and Memory Content into independent pages with distinct themes and data sources.

## Architecture

### Page Structure

```
┌─────────────────────────────────────────────────────────────┐
│              Web Visualization Server                     │
│                  (viz_server_local_js.py)             │
└─────────────────────────────────────────────────────────────┘
                           │
          ┌────────────────┴────────────────┐
          │                                 │
    ▼ Knowledge Graph                ▼ Memory Content
    /api/graph                      /api/memory
         │                                 │
┌────────▼─────────┐         ┌──────────▼──────────┐
│  KNOWLEDGE_CONCEPTS│         │   MEMORY_NODES        │
│  Table             │         │   Table              │
└────────────────────┘         └─────────────────────┘
         │                                 │
    ┌────▼─────┐                 ┌────▼─────┐
    │ 44 Nodes  │                 │  14 Nodes │
    └────┬─────┘                 └────┬─────┘
         │                              │
    HTTP Routes                   HTTP Routes
    /, /graph                      /memory
```

### Data Source Mapping

| Page | Route | Table | Key Fields | Node Count |
|-------|--------|-------|-------------|-------------|
| **Knowledge Graph** | `/`, `/graph` | `KNOWLEDGE_CONCEPTS` | `CONCEPT_ID`, `CONCEPT_TYPE`, `CONCEPT_NAME` | 44 |
| **Memory Content** | `/memory` | `MEMORY_NODES` | `NODE_ID`, `NODE_TYPE`, `LABEL` | 14 |

### Database Schema Differences

**CRITICAL**: `KNOWLEDGE_CONCEPTS` and `MEMORY_NODES` use different field names.

```sql
-- KNOWLEDGE_CONCEPTS Schema
CONCEPT_ID         NUMBER PRIMARY KEY
CONCEPT_NAME       VARCHAR2(200)
CONCEPT_TYPE       VARCHAR2(50)
CATEGORY           VARCHAR2(100)
TITLE              VARCHAR2(500)
DESCRIPTION         CLOB
EMBEDDING          VECTOR

-- MEMORY_NODES Schema
NODE_ID            Primary Key
NODE_TYPE          VARCHAR2
LABEL              VARCHAR2
PROPERTIES          CLOB (JSON)
EMBEDDING          VECTOR
```

### Field Mapping Code

```python
# Knowledge Graph Node Mapping
for row in cursor.fetchall():
    concept_id, concept_type, concept_name = row
    nodes.append({
        'id': str(concept_id),
        'label': str(concept_name)[:50] if concept_name else '',
        'group': str(concept_type) if concept_type else 'UNKNOWN',
        'color': get_node_color(concept_type),
        'title': f"{concept_type}: {concept_name}" if concept_name else concept_type
    })

# Memory Content Node Mapping
for row in cursor.fetchall():
    node_id, node_type, label = row
    nodes.append({
        'id': str(node_id),
        'label': str.()[:50] if label else '',
        'group': str(node_type) if node_type else 'UNKNOWN',
        'color': get_node_color(node_type),
        'title': f"{node_type}: {label}" if label else node_type
    })
```

## API Endpoints

### Knowledge Graph API

**Endpoint**: `GET /api/graph`

**Returns**: JSON with nodes and edges from `KNOWLEDGE_CONCEPTS`

```json
{
  "nodes": [
    {
      "id": "1",
      "label": "Test Concept",
      "group": "FACT",
      "color": "#e74c3c",
      "title": "FACT: Test Concept"
    }
  ],
  "edges": [...]
}
```

### Memory Content API

**Endpoint**: `GET /api/memory`

**Returns**: JSON with nodes and edges from `MEMORY_NODES`

```json
{
  "nodes": [
    {
      "id": "1",
      "label": "OracleDB",
      "group": "Database",
      "color": "#3498db",
      "title": "Database: OracleDB"
    }
  ],
  "edges": [...]
}
```

### Node Details API

**Endpoint**: `GET /api/node/{id}`

**Purpose**: Fetch detailed node information including PROPERTIES (CLOB) and embedding status

**Response**:
```json
{
  "node_id": "1",
  "node_type": "Database",
  "label": "OracleDB",
  "properties": {
    "version": "26ai",
    "custom_field": "value"
  },
  "has_embedding": false
}
```

**Backend Implementation**:
```python
def send_node_details(self, node_id):
    """Send detailed node information including PROPERTIES field"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT NODE_ID, NODE_TYPE, LABEL, PROPERTIES, EMBEDDING
        FROM MEMORY_NODES
        WHERE NODE_ID = :node_id
    """
    cursor.execute(query, {'node_id': node_id})
    row = cursor.fetchone()
    
    if row:
        node_id, node_type, label, properties, embedding = row
        
        # Convert CLOB to string
        if properties:
            properties_text = str(properties)
        else:
            properties_text = ""
        
        # Parse JSON properties if available
        properties_json = {}
        if properties_text:
            try:
                properties_json = json.loads(properties_text)
            except:
                properties_json = {'raw': properties_text}
        
        result = {
            'node_id': str(node_id),
            'node_type': str(node_type) if node_type else None,
            'label': str(label) if label else '',
            'properties': properties_json,
            'has_embedding': embedding is not None
        }
        
        self.wfile.write(json.dumps(result).encode('utf-8'))
```

## Frontend Implementation

### Page Theme Differentiation

```javascript
// Page-specific configuration
if (page_type === 'knowledge') {
    page_title = 'Knowledge Graph';
    page_subtitle = 'Knowledge Graph Visualization';
    page_emoji = '🧠';
    page_bg = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
    api_endpoint = '/api/graph';
} else {  // memory
    page_title = 'Memory Content';
    page_subtitle = 'Memory Content Visualization';
    page_emoji = '💾';
    page_bg = 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)';
    api_endpoint = '/api/memory';
}
```

### Navigation Bar

```html
<div style="margin: 15px 0;">
    <a href="/graph" class="nav-link {'active' if page_type === 'knowledge' else ''}">
        🧠 知识图谱
    </a>
    <a href="/memory" class="nav-link {'active' if page_type === 'memory' else ''}">
        💾 记忆内容
    </a>
</div>
```

**CSS Styling**:
```css
.nav-link {
    display: inline-block;
    margin: 5px 5px 5px 0;
    padding: 8px 15px;
    background: rgba(255,255,255,0.2);
    border-radius: 5px;
    color: white;
    text-decoration: none;
    transition: background 0.3s;
}

.nav-link:hover {
    background: rgba(255,255,255,0.3);
}

.nav-link.active {
    background: rgba(255,255,255,0.4);
}
```

### Node Click Handler

```javascript
network.on('click', function(params) {
    if (params.nodes.length > 0) {
        var node = nodes.get(params.nodes[0]);
        document.getElementById('node-id').textContent = node.id;
        document.getElementById('node-type').textContent = node.group || 'unknown';
        document.getElementById('node-label').textContent = node.label;
        document.getElementById('node-info').classList.add('active');
        
        // Fetch detailed node information from server
        fetch('/api/node/' + node.id)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    document.getElementById('properties-content').textContent = 
                        '错误: ' + data.error;
                    return;
                }
                
                // Display properties
                if (data.properties && Object.keys(data.properties).length > 0) {
                    document.getElementById('properties-content').textContent = 
                        JSON.stringify(data.properties, null, 2);
                } else {
                    document.getElementById('properties-content').textContent = 
                        '无详细信息';
                }
                
                // Display embedding status
                if (data.has_embedding) {
                    document.getElementById('embedding-status').innerHTML = 
                        '<span style="color: #51cf66;">✓ 包含向量嵌入</span>';
                } else {
                    document.getElementById('embedding-status').innerHTML = 
                        '<span style="color: #ff6b6b;">✗ 无向量嵌入</span>';
                }
            })
            .catch(error => {
                document.getElementById('properties-content').textContent = 
                    '加载失败: ' + error.message;
            });
    }
});
```

## Caching Strategy

### Dual Cache Architecture

```python
# Knowledge Graph Cache
_graph_cache = {
    'data': None,
    'timestamp': None,
    'ttl': 300  # 5 minutes
}

# Memory Content Cache
_memory_cache = {
    'data': None,
    'timestamp': None,
    'ttl': 300  # 5 minutes
}
```

**Benefits**:
- Independent data loading prevents cache conflicts
- Each page maintains its own TTL
- Thread-safe access with `_cache_lock`
- 4500x performance improvement (90s → 0.020s)

## Performance Metrics

### Current Deployment

| Metric | Knowledge Graph | Memory Content |
|---------|----------------|-----------------|
| **Node Count** | 44 | 14 |
| **Edge Count** | 40 (auto-generated) | 1 (auto-generated) |
| **Query Time** | ~0.020s | ~0.020s |
| **Cache TTL** | 300s | 300s |
| **Connection Pool** | min=2, max=5 | min=2, max=5 |

### Optimization Stack

1. **Python `oracledb` Driver** - Direct database connection (no SQLcl subprocess overhead)
2. **Connection Pooling** - Reuse connections (min=2, max=5)
3. **Data Caching** - 5-minute TTL with thread-safe access
4. **Local JavaScript** - `vis-network.min.js` served from `/static/` (no CDN dependency)
5. **Pre-loading** - Data loaded at server startup

## Troubleshooting

### Issue: Knowledge Graph Shows 0 Nodes

**Symptoms**:
- `/api/graph` returns `{"nodes": [], "edges": []}`
- Page displays empty graph

**Diagnosis**:
```bash
# Check if KNOWLEDGE_CONCEPTS table has data
echo "SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS" | \
    sql openclaw/hermes@//10.10.10.130:1521/openclaw

# Expected: COUNT > 0 (should be 44 based on known data)
```

**Common Causes**:
1. **Wrong field names** - Using `NODE_ID` instead of `CONCEPT_ID`
2. **Wrong table name** - Querying `MEMORY_NODES` instead of `KNOWLEDGE_CONCEPTS`
3. **Empty table** - Data not loaded yet

**Solutions**:
```sql
-- Verify correct table name
SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS;

-- Verify correct field names
DESCRIBE KNOWLEDGE_CONCEPTS;
-- Expected: CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE

-- Test query directly
SELECT CONCEPT_ID, CONCEPT_TYPE, CONCEPT_NAME 
FROM KNOWLEDGE_CONCEPTS 
FETCH FIRST 5 ROWS ONLY;
```

### Issue: Node Details API Returns Error

**Symptoms**:
- Clicking node shows "错误: Node not found"
- `/api/node/{id}` returns 404

**Diagnosis**:
```bash
# Check if node ID exists in MEMORY_NODES
echo "SELECT NODE_ID FROM MEMORY_NODES WHERE NODE_ID = 1" | \
    sql openclaw/hermes@//10.10.10.130:1521/openclaw
```

**Solutions**:
1. **Verify node ID** - Ensure ID exists in correct table
2. **Check table permissions** - Verify user has SELECT access
3. **Check CLOB reading** - Ensure PROPERTIES field is accessible

### Issue: Mixed Data Sources

**Symptoms**:
- Knowledge Graph page shows memory nodes
- Memory Content page shows knowledge concepts

**Diagnosis**:
```python
# Check load_graph_data() queries correct table
# Should use: KNOWLEDGE_CONCEPTS
# NOT: MEMORY_NODES

# Check load_memory_data() queries correct table
# Should use: MEMORY_NODES
# NOT: KNOWLEDGE_CONCEPTS
```

## Verification Checklist

Before deploying v1.4.0:

- [ ] `KNOWLEDGE_CONCEPTS` table uses `CONCEPT_ID`, `CONCEPT_TYPE`, `CONCEPT_NAME`
- [ ] `MEMORY_NODES` table uses `NODE_ID`, `NODE_TYPE`, `LABEL`
- [ ] `/api/graph` returns 44 nodes (knowledge data)
- [ ] `/api/memory` returns 14 nodes (memory data)
- [ ] `/api/node/{id}` returns PROPERTIES JSON
- [ ] `/` route redirects to knowledge graph (purple theme)
- [ ] `/memory` route shows memory content (pink theme)
- [ ] Navigation buttons work correctly
- [ ] Node click displays detailed properties
- [ ] Connection pool status: OK
- [ ] Cache mechanism working (second request faster)
- [ ] Local JS file loaded (no CDN)

## Access URLs

| Page | URL | Theme |
|-------|-----|--------|
| **Knowledge Graph** | http://10.10.10.135:8000/ | Purple gradient |
| **Knowledge Graph** | http://10.10.10.135:8000/graph | Purple gradient |
| **Memory Content** | http://10.10.10.135:8000/memory | Pink gradient |
| **Health Check** | http://10.10.10.135:8000/api/health | - |

## Related Documentation

- [README_VIZ_SERVER.md](../README_VIZ_SERVER.md) - Web visualization server guide
- [web-visualization-performance-optimization.md](web-visualization-performance-optimization.md) - 4500x optimization details
- [web-visualization-node-details-enhancement.md](web-visualization-node-details-enhancement.md) - Node details API
