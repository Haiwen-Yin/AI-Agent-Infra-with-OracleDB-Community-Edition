# Web Visualization Server Guide

**Author**: Haiwen Yin (胖头鱼 🐟)  
**Date**: 2026-05-12  
**Version**: v1.0.0

---

## Overview

The Web Visualization Server (`start_web_server.py`) enables remote access to knowledge graph visualizations without requiring a GUI on the Oracle Database server. This is critical for headless server environments or when you need to share visualizations with team members.

## Use Cases

1. **Headless Server Environment**: Oracle DB server has no graphical interface (X11/X Window System not installed)
2. **Remote Access**: Access visualizations from any location without SSH tunneling
3. **Team Collaboration**: Share visualization with multiple team members simultaneously
4. **Production Monitoring**: Embed visualization in monitoring dashboards

## Quick Start

### Basic Usage

```bash
cd /root/.hermes/skills/oracle-memory-by-yhw
python3 start_web_server.py
```

Default behavior:
- Port: 8000
- Username: `admin`
- Password: `admin123`
- Auto-opens browser on local machine
- Generates fresh visualization on startup

### Access URLs Displayed

Server startup shows:
```
====================================
Oracle Memory System - Web Visualization Server
Version v1.0.0 | Author: Haiwen Yin (胖头鱼 🐟)
====================================

Step 1: Generate Visualization
----------------------------------------------------------------------
Authenticating admin...
Authenticated as admin (admin)
Fetching knowledge graph...
   Found 23 concepts, 45 relationships
Generating visualization: visualization_output/graph_1715482345.html
Visualization generated successfully

Step 2: Start Web Server
----------------------------------------------------------------------
Starting HTTP server on port 8000...
Serving directory: visualization_output

Server started successfully!

Access URLs:
   Local:    http://localhost:8000
   Network:  http://10.10.10.130:8000
   Hostname:  http://dbserver.example.com:8000

To access from external machines:
   1. Make sure firewall allows port 8000
   2. Use URL: http://<your-ip-address>:8000
   3. Your IP address: 10.10.10.130

Press Ctrl+C to stop the server
======================================================================
```

## Advanced Options

### Custom Port

```bash
python3 start_web_server.py --port 9000
```

If port 9000 is occupied, server automatically finds next available port.

### Custom Credentials

```bash
python3 start_web_server.py --username myuser --password mypassword
```

Use non-default credentials for enhanced security.

## Firewall Configuration

### Check Firewall Status

```bash
firewall-cmd --list-all
```

### Open Port (Temporary - Lost on Reboot)

```bash
firewall-cmd --add-port=8000/tcp
```

### Open Port (Permanent - Survives Reboot)

```bash
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload
```

### Verify Port Open

```bash
firewall-cmd --list-ports
```

Expected output: `8000/tcp`

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│         Web Visualization Server Flow                   │
└─────────────────────────────────────────────────────────┘

1. Start Script
   │
   ├─► Authenticate with Oracle Database (admin/admin123)
   │   └─► SQL: SELECT FROM VIZ_USERS
   │
   ├─► Fetch Knowledge Graph
   │   ├─► SELECT FROM KNOWLEDGE_CONCEPTS (nodes)
   │   └─► SELECT FROM KNOWLEDGE_GRAPH (edges)
   │
   ├─► Generate Interactive HTML
   │   ├─► Use pyvis.network.Network()
   │   ├─► Add nodes with color/size/shape coding
   │   ├─► Add edges with arrows and labels
   │   └─► Save to visualization_output/graph_<timestamp>.html
   │
   └─► Start HTTP Server
       ├─► Bind to 0.0.0.0:8000 (all interfaces)
       ├─► Serve files from visualization_output/
       ├─► Auto-open browser http://localhost:8000
       └─► Serve forever until Ctrl+C
```

### File Structure

```
visualization_output/
├── index.html              # Landing page with stats
├── graph_1715482345.html  # Latest interactive graph
└── statistics_1715482345.json  # Graph metrics
```

### HTTP Server Details

- **Handler**: `CORSHTTPRequestHandler` - Custom SimpleHTTPRequestHandler
- **CORS Enabled**: Yes (`Access-Control-Allow-Origin: *`)
- **Supported Methods**: GET, OPTIONS
- **Authentication**: Single-user at startup (no per-request auth)

## Features

### ✅ Remote Access Without GUI

Works on any server with Python 3.x installed, no X11 or display server required.

### ✅ CORS Support

Allows cross-origin requests for embedding in dashboards or third-party web applications.

### ✅ Auto-Generation

Generates fresh visualization on every server start, ensuring data currency.

### ✅ Auto-Browser Launch

Automatically opens default browser on the machine where script is started.

### ✅ Port Auto-Discovery

If specified port is occupied, automatically finds next available port.

### ✅ Real-Time Statistics

Landing page displays:
- Total nodes
- Total edges
- Generation timestamp
- User role

## Comparison with Other Visualization Methods

| Method | Requires GUI | Remote Access | Performance | Interactive | Setup Complexity |
|--------|--------------|---------------|--------------|--------------|-------------------|
| `launch_viz_simple.py` | ✅ Yes | ❌ No | Fast | ✅ Yes | Low |
| `knowledge_graph_interactive.py` | ✅ Yes | ❌ No | Medium | ✅ Yes | Medium |
| **`start_web_server.py`** | ❌ No | ✅ Yes | Medium | ✅ Yes | Low |
| `knowledge_graph_visualizer.py` | ❌ No | ❌ No | Fast | ❌ No | Low |

## Troubleshooting

### Issue: Port Already in Use

**Error**: `Address already in use`

**Solution**: Let server auto-discover available port or specify different port:

```bash
python3 start_web_server.py --port 9000
```

### Issue: External Access Failed

**Symptom**: Browser shows "Connection refused" or "Site can't be reached"

**Diagnosis Steps**:
1. Check if server is running: `netstat -tlnp | grep 8000`
2. Check firewall: `firewall-cmd --list-ports`
3. Test locally: `curl http://localhost:8000`
4. Check IP address: `ip addr show`

**Solutions**:
```bash
# Open firewall port
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload

# Verify server listening
netstat -tlnp | grep 8000
# Expected: tcp  0  0  0.0.0.0:8000  0.0.0.0:*  LISTEN  <pid>/python3

# Test connection
curl http://localhost:8000
```

### Issue: Authentication Failed

**Error**: `Authentication failed`

**Diagnosis**:
```bash
cd /root/.hermes/skills/oracle-memory-by-yhw/security
python3 auth_db_working.py list-users
```

**Solution**: Reset admin password:

```bash
python3 auth_db_working.py change-password admin <old> <new>
```

### Issue: No Data in Visualization

**Symptom**: Graph loads but shows 0 nodes and 0 edges

**Diagnosis**:
```bash
/root/sqlcl/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw << 'EOF'
SELECT COUNT(*) as concepts FROM KNOWLEDGE_CONCEPTS;
SELECT COUNT(*) as relationships FROM KNOWLEDGE_GRAPH;
EXIT;
EOF
```

**Solution**: Populate knowledge base with data:

```bash
python3 scripts/knowledge_base_api.py create_concept "Test Concept" "FACT" "Test description"
```

### Issue: Browser Doesn't Open Automatically

**Symptom**: Server starts but browser doesn't open

**Solution**: Manually open browser and navigate to:

```
http://localhost:8000
```

Or use IP address:

```
http://10.10.10.130:8000
```

### Issue: Module Not Found

**Error**: `ModuleNotFoundError: No module named 'pyvis'`

**Solution**: Install dependencies:

```bash
pip3 install networkx pyvis
```

## Security Considerations

### Default Credentials

⚠️ **CRITICAL**: Default credentials (`admin`/`admin123`) are for development only.

**Change Immediately**:
```bash
cd /root/.hermes/skills/oracle-memory-by-yhw/security
python3 auth_db_working.py change-password admin admin123 <strong_password>
```

### Firewall Exposure

Opening ports exposes service to network. Consider:

1. **Restrict to Specific IPs** (using iptables):
```bash
iptables -A INPUT -p tcp --dport 8000 -s <allowed_ip> -j ACCEPT
iptables -A INPUT -p tcp --dport 8000 -j DROP
```

2. **Use Reverse Proxy** (Nginx/Apache):
   - Terminate SSL at proxy
   - Add basic HTTP auth
   - Rate limiting

3. **VPN/SSH Tunnel**:
   - Don't expose publicly
   - Access via SSH tunnel: `ssh -L 8000:localhost:8000 user@server`

### Audit Logging

Access to knowledge graph is logged in `VIZ_ACCESS_LOGS` table:

```sql
SELECT * FROM VIZ_ACCESS_LOGS
ORDER BY ACCESS_TIME DESC
FETCH FIRST 20 ROWS ONLY;
```

## Production Deployment

### Recommended Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Production Deployment Setup                   │
└─────────────────────────────────────────────────────────┘

Oracle DB Server (10.10.10.130)
│
├─► Oracle Database 26ai
│   ├─► KNOWLEDGE_CONCEPTS (data)
│   └─► KNOWLEDGE_GRAPH (data)
│
└─► Web Visualization Server (port 8000)
    │
    ├─► Reverse Proxy (Nginx, port 80/443)
    │   ├─► SSL/TLS termination
    │   ├─► Basic HTTP authentication
    │   └─► Rate limiting
    │
    └─► Client Browsers
        ├─► Desktop (Chrome, Firefox, Edge, Safari)
        └─► Mobile (Chrome Mobile, Safari Mobile)
```

### Nginx Configuration Example

```nginx
server {
    listen 80;
    server_name knowledge-graph.example.com;
    
    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name knowledge-graph.example.com;
    
    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/knowledge-graph.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/knowledge-graph.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    
    # Basic Authentication
    auth_basic "Knowledge Graph Access";
    auth_basic_user_file /etc/nginx/.htpasswd;
    
    # Proxy to Web Visualization Server
    location / {
        proxy_pass http://10.10.10.130:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Create Nginx User

```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd graph_user
# Enter password when prompted
```

### Systemd Service (Auto-Start)

Create `/etc/systemd/system/knowledge-graph-viz.service`:

```ini
[Unit]
Description=Oracle Knowledge Graph Visualization Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/.hermes/skills/oracle-memory-by-yhw
ExecStart=/usr/bin/python3 start_web_server.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable knowledge-graph-viz.service
sudo systemctl start knowledge-graph-viz.service
sudo systemctl status knowledge-graph-viz.service
```

## Performance Tuning

### Large Graph Optimization

For graphs with 500+ nodes:

1. **Reduce Node Size**: Edit `start_web_server.py` and adjust `size` parameter in `add_node()`
2. **Simplify Physics**: Use static layout instead of physics-based
3. **Enable Filtering**: Add node/edge type filters in HTML

### Network Optimization

For remote access over slow networks:

1. **Enable Compression**: Add gzip to Nginx reverse proxy
2. **Lazy Loading**: Implement incremental node loading
3. **CDN Caching**: Cache static assets

## Summary

The Web Visualization Server enables remote, GUI-free access to interactive knowledge graph visualizations. It's production-ready with:

- ✅ No server GUI required
- ✅ Remote browser access
- ✅ CORS support
- ✅ Auto-generation
- ✅ Firewall integration
- ✅ Reverse proxy compatibility
- ✅ Systemd service support

---

## ⚠️ Critical Pitfalls (Lessons Learned 2026-05-12)

### 1. `_graph_cache` Structure

**Problem**: The cache is NOT `None` when empty - it's a dict with structure:
```python
_graph_cache = {
    'data': None,      # Actual graph data (nodes/edges)
    'timestamp': None,  # When data was loaded
    'ttl': 300         # Time-to-live in seconds
}
```

**Wrong Check**:
```python
if _graph_cache is None:  # ALWAYS False - cache is a dict
    return error
```

**Correct Check**:
```python
if _graph_cache['data'] is None:  # Check actual data
    return error
```

### 2. SQLcl Subprocess Timeout

**Problem**: Using subprocess to call sqlcl CLI causes 90+ second timeouts

**Solution**: Use Python `oracledb` driver directly:
```python
import oracledb
pool = oracledb.create_pool(user=user, password=pwd, dsn=dsn, min=2, max=5)
conn = pool.acquire()
cursor = conn.cursor()
cursor.execute("SELECT ...")
rows = cursor.fetchall()
```

**Performance**: 90s → 0.020s (4500x speedup)

### 3. Minimal Modification Principle

**Rule**: When fixing viz server, only modify what's specifically requested. Preserve all existing features.

**Example**:
```python
# ❌ WRONG - rewriting entire server when only login labels needed
with open('server.py', 'w') as f:
    f.write(new_code)  # Destroys existing features

# ✅ CORRECT - surgical patch
content = content.replace(
    '<label>Username</label>',
    '<label>用户名 / Username</label>'
)
```

### 4. Complete Feature Set Required

All features must work together:
- Login page (bilingual)
- Session management
- `/graph` and `/memory` routes
- Graph/Memory toggle buttons
- Language toggle buttons
- Node detail panel
- Data loading (oracledb)

**Checklist**:
```bash
# Test login
curl -c cookies.txt -X POST -d "username=admin&password=admin123" http://localhost:8000/api/login

# Test graph page
curl -b cookies.txt http://localhost:8000/graph | grep "Knowledge Graph"

# Test memory page
curl -b cookies.txt http://localhost:8000/memory | grep "Memory Content"

# Test API data
curl -b cookies.txt http://localhost:8000/api/graph | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['nodes']), len(d['edges']))"
```

---

**Last Updated**: 2026-05-12 (Added critical pitfalls section)
**Related Session**: [Viz Server Restoration 2026-05-12](references/viz-server-restoration-2026-05-12-complete.md)
**Related Files**:
- `/root/.hermes/skills/oracle-memory-by-yhw/start_web_server.py` - Main server script
- `/root/.hermes/skills/oracle-memory-by-yhw/security/auth_db_working.py` - Authentication module
- `/root/.hermes/skills/oracle-memory-by-yhw/scripts/knowledge_graph_interactive.py` - Visualization generation
