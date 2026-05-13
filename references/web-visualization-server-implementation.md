# Web Visualization Server Implementation

**Author**: Haiwen Yin (胖头鱼 🐟 / yhw)  
**Date**: 2026-05-12  
**Session**: Visualization server development for external browser access

---

## Overview

Web visualization server provides **external browser access** to Oracle Memory System knowledge graph visualization without requiring a graphical interface on the server. This enables users to view and interact with the knowledge graph from any machine with a web browser.

---

## Architecture

### Server Implementation

**Framework**: Python `http.server` module (standard library, no dependencies)

**Core Components**:

1. **HTTP Request Handler** (`GraphAPIHandler`)
   - CORS support for external access
   - Static HTML serving
   - Graph data API endpoint
   - Health check endpoint

2. **Graph Data Loader**
   - Queries Oracle database for nodes and edges
   - Caches data in memory for performance
   - Generates visualization-friendly JSON format

3. **HTML/JavaScript Frontend**
   - Embedded Vis.js for graph visualization
   - Interactive drag-and-drop interface
   - Node detail sidebar
   - Physics-based layout

---

## Deployment

### Server Information

| Property | Value |
|----------|-------|
| **Server Host** | 10.10.10.135 (Hermes Agent server) |
| **Port** | 8000 |
| **Database Host** | 10.10.10.130 (Oracle Database) |
| **Access URL** | http://10.10.10.135:8000 |

### Quick Start

```bash
cd /root/.hermes/skills/oracle-memory-by-yhw
python3 viz_server_simple.py
```

**Output**:
```
======================================================================
         Oracle Memory System - Simple Web Visualization Server
======================================================================
✅ Starting server on http://0.0.0.0:8000
   Local:   http://localhost:8000
   Network: http://10.10.10.135:8000
======================================================================
```

### Access from External Browser

1. **Start the server** on Hermes Agent machine (10.10.10.135)
2. **Open browser** on any machine
3. **Navigate to**: http://10.10.10.135:8000
4. **Login**: Not required for basic version (authentication available)

---

## API Endpoints

### GET /

Returns main HTML page with embedded Vis.js visualization.

**Response**: HTML page

### GET /api/health

Health check endpoint for monitoring.

**Response**: 
```json
{"status": "ok"}
```

### GET /api/graph

Returns graph data (nodes and edges) for visualization.

**Response**: 
```json
{
  "nodes": [
    {
      "id": "1",
      "label": "Oracle Memory",
      "group": "SYSTEM",
      "color": "#e74c3c"
    }
  ],
  "edges": [
    {
      "from": "1",
      "to": "2",
      "label": "contains"
    }
  ]
}
```

---

## Database Schema

### MEMORY_NODES Table

**Verified Schema (2026-05-12)**:

| Column | Type | Description |
|---------|-------|-------------|
| NODE_ID | NUMBER | Primary key (NOT NULL) |
| LABEL | VARCHAR2(100) | Node label/name |
| NODE_TYPE | VARCHAR2(50) | Type classification |
| PROPERTIES | CLOB | Additional properties (JSON) |
| EMBEDDING | VECTOR | Vector embedding (1024 dimensions) |

**IMPORTANT**: 
- Column is `NODE_ID` (not `ID`)
- Use `NODE_ID` in all SQL queries
- Use `NODE_TYPE` (not `node_type`)

### Sample Query

```sql
SELECT NODE_ID, NODE_TYPE, LABEL 
FROM MEMORY_NODES 
ORDER BY NODE_ID
```

---

## Known Issues & Solutions

### Issue 1: Database Query Timeout

**Problem**: SQLcl query timeout (90 seconds) when loading graph data.

**Root Causes**:
1. Large dataset in MEMORY_NODES table
2. Network latency to 10.10.10.130:1521
3. SQLcl startup overhead per query

**Current Solution** (viz_server_simple.py):
- Use **sample data** instead of querying database
- Fallback to demonstration data for reliability

**Future Solutions**:
1. **Limit query size**: `WHERE ROWNUM <= 100`
2. **Connection pooling**: Reuse SQLcl processes
3. **Pre-load data**: Cache at server startup
4. **Pagination**: Load data in chunks

### Issue 2: Memory Schema Mismatch

**Problem**: Column names assumed incorrectly caused ORA-00904 errors.

**Assumed Schema** (INCORRECT):
```sql
SELECT ID, node_type, label FROM memory_nodes
-- ORA-00904: "ID": invalid identifier
```

**Actual Schema** (CORRECT):
```sql
SELECT NODE_ID, NODE_TYPE, LABEL FROM MEMORY_NODES
-- Works correctly
```

**Solution**: Always verify schema with `DESCRIBE` before coding:

```bash
echo "DESCRIBE MEMORY_NODES" | /root/sqlcl/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw
```

### Issue 3: Background Server Management

**Problem**: Running server in background with nohup/disown fails.

**Hermes Agent Solution**: Use `terminal(background=true)` for long-lived processes:

```python
# ✅ CORRECT (Hermes Agent)
terminal(background=true, command="python3 viz_server_simple.py")

# ❌ INCORRECT (Shell syntax)
nohup python3 viz_server_simple.py > /tmp/log.log 2>&1 &
```

### Issue 4: Log File Access

**Problem**: Background process output not visible in logs.

**Solution**: Use process poll and log commands:

```python
# Check process status
process(action='poll', session_id='proc_...')

# Get recent log output
process(action='log', limit=50, session_id='proc_...')
```

---

## Visualization Features

### Interactive Controls

| Interaction | Description |
|-------------|-------------|
| **Drag Nodes** | Move nodes to rearrange layout |
| **Scroll** | Zoom in/out of graph |
| **Click** | View node details in sidebar |
| **Hover** | Show quick information tooltip |

### Color Coding (Node Types)

| Type | Color | Meaning |
|-------|-------|---------|
| SYSTEM | 🔴 #e74c3c | System components |
| FEATURE | 🟢 #2ecc71 | Feature modules |
| SECURITY | 🟣 #9b59b6 | Security features |
| CONCEPT | 🟠 #f39c12 | Knowledge concepts |
| ENTITY | 🔵 #3498db | Named entities |

### Physics Engine

**Configuration**:
```javascript
barnesHut: {
  gravitationalConstant: -2000,
  centralGravity: 0.3,
  spring: 0.05,
  damping: 0.09,
  springLength: 95
}
```

**Behavior**: Automatically positions nodes based on connections, creating organic layout.

---

## Security Considerations

### Current Status (viz_server_simple.py)

- ✅ No authentication required (for demo)
- ⚠️ Open CORS policy (`Access-Control-Allow-Origin: *`)
- ⚠️ No rate limiting
- ⚠️ No request logging

### Production Deployment Recommendations

1. **Enable authentication** (use oracle-memory-by-yhw security module)
2. **Restrict CORS** to specific origins
3. **Add rate limiting** (e.g., 100 requests/minute)
4. **Implement HTTPS** for encrypted transmission
5. **Add request logging** for audit trail
6. **Use firewall rules** to restrict access

### Firewall Configuration

```bash
# Open port 8000 on Hermes Agent server (10.10.10.135)
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload

# Or allow only from specific network
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.10.10.0/24" port protocol="tcp" port="8000" accept'
firewall-cmd --reload
```

---

## Server Files

| File | Purpose | Status |
|------|---------|--------|
| `viz_server_simple.py` | Simple server with sample data | ✅ Working |
| `simple_viz_server_v2.py` | Version 2 with database query | ⚠️ Timeout issues |
| `start_web_server.py` | Original launcher | ⚠️ Legacy |

**Recommended Use**: `viz_server_simple.py` for reliable demo access.

---

## Performance Metrics

### Current Performance (Sample Data)

| Metric | Value |
|--------|-------|
| **Page Load Time** | < 1 second |
| **Graph Rendering** | < 2 seconds |
| **Interaction Latency** | < 50ms |
| **Memory Usage** | ~50MB |

### Expected Performance (With Database)

| Metric | Target |
|--------|--------|
| **Page Load Time** | < 2 seconds |
| **Graph Rendering** | < 5 seconds |
| **Database Query** | < 30 seconds (optimized) |
| **Cache Hit Rate** | > 90% |

---

## Troubleshooting

### Problem: Cannot Access from External Machine

**Symptoms**: `curl: (7) Failed to connect to host`

**Checklist**:

1. ✅ **Verify server is running**:
   ```bash
   ps aux | grep viz_server
   ```

2. ✅ **Check port is listening**:
   ```bash
   ss -tlnp | grep 8000
   # Expected: LISTEN 0 5 0.0.0.0:8000
   ```

3. ✅ **Test local access**:
   ```bash
   curl http://localhost:8000/api/health
   # Expected: {"status": "ok"}
   ```

4. ✅ **Check firewall**:
   ```bash
   firewall-cmd --list-ports | grep 8000
   # Should show 8000/tcp is open
   ```

5. ✅ **Verify network connectivity**:
   ```bash
   ping 10.10.10.135
   traceroute 10.10.10.135
   ```

### Problem: Server Not Starting

**Symptoms**: Background process exits immediately

**Check logs**:
```bash
cat /tmp/viz_server.log
```

**Common causes**:
- Port already in use (8000)
- Python module not installed
- File permissions issue

**Solution**:
```bash
# Kill existing process
pkill -f viz_server_simple

# Start fresh
cd /root/.hermes/skills/oracle-memory-by-yhw
python3 viz_server_simple.py
```

### Problem: Graph Shows No Data

**Symptoms**: Empty graph displayed in browser

**Check database**:
```bash
echo "SELECT COUNT(*) FROM MEMORY_NODES" | /root/sqlcl/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw
```

**Solutions**:
1. Add sample data to database
2. Verify table name is correct (MEMORY_NODES not memory_nodes)
3. Check column names (NODE_ID, NODE_TYPE, LABEL)

---

## Future Enhancements

### Planned Features

1. **Real-time Updates** - WebSocket for live graph changes
2. **Authentication Integration** - Use oracle-memory-by-yhw auth module
3. **Advanced Filtering** - Filter by type, date, confidence
4. **Export Functionality** - Download graph as PNG/SVG/PDF
5. **Search Interface** - Text search with highlighting
6. **Multi-view Layouts** - Force-directed, circular, hierarchical
7. **Performance Monitoring** - Query time, render time metrics
8. **Mobile Support** - Responsive design for mobile devices

### Database Optimization

1. **Materialized View** - Pre-compute graph structure
2. **Vector Search** - Find similar nodes in visualization
3. **Incremental Loading** - Load nodes on demand
4. **Edge Caching** - Cache relationship queries

---

## References

- **Vis.js Documentation**: https://visjs.org/
- **Python http.server**: https://docs.python.org/3/library/http.server.html
- **SQLcl Documentation**: https://docs.oracle.com/en/database/oracle/sqlcl/
- **oracle-memory-by-yhw Skill**: Complete Memory System implementation
