# Web Visualization Browser Troubleshooting

## Problem: Page Loading Issue (Spinner Never Stops)

**Symptom**: User visits http://10.10.10.135:8000 but page keeps spinning, graph never displays.

## Root Cause Analysis

### 1. Iframe Loading Issues (viz_server_optimized.py)
**Problem**: Main page uses iframe to load graph, but iframe content fails to load.

**Diagnose**:
```javascript
// Add to iframe's HTML
<script>
  console.log('Iframe loaded');
  window.parent.postMessage({status: 'loaded'}, '*');
</script>

// In main page
window.addEventListener('message', function(e) {
  console.log('Received iframe message:', e.data);
});
</script>
```

**Solution**: Use `viz_server_single_fixed.py` (no iframe approach).

### 2. CDN Loading Failure (vis-network.js)
**Problem**: Cannot load vis-network library from CDN.

**Symptoms**:
- Browser console shows: `Failed to load resource: unpkg.com`
- OR: `vis is not defined`
- OR: `ReferenceError: vis is not defined`

**Diagnose**:
1. Open browser developer tools (F12)
2. Go to Console tab
3. Look for errors like:
   - `GET https://unpkg.com/... net::ERR_NAME_NOT_RESOLVED`
   - `ReferenceError: vis is not defined`
4. Check Network tab:
   - See if `vis-network.min.js` request failed (red)

**Solution A - Use viz_server_debug.py**:
Has multi-CDN fallback and debug panel:
```bash
cd /root/.hermes/skills/oracle-memory-by-yhw
python3 viz_server_debug.py
```

Check left sidebar "调试信息" panel:
- `CDN: ✓ unpkg.com` or `CDN: ✗ unpkg.com 失败`
- `vis-network: ✓ 已加载` or `vis-network: ✗ 加载失败`

**Solution B - Manual CDN Test**:
```bash
# Test CDN accessibility
curl -I https://unpkg.com/vis-network@latest/dist/vis-network.min.js
curl -I https://cdnjs.cloudflare.com/ajax/libs/vis-network/2.1.9/vis-network.min.js
```

If both fail, server has no internet access.

**Solution C - Localize vis-network.js**:
Download library to server (requires internet once):
```bash
# Download vis-network
wget https://unpkg.com/vis-network@2.1.9/dist/vis-network.min.js -O /root/.hermes/skills/oracle-memory-by-yhw/static/vis-network.min.js

# Modify HTML to use local copy
# Change: <script src="https://unpkg.com/..."></script>
# To: <script src="/static/vis-network.min.js"></script>
```

### 3. Data Loading Failure
**Problem**: `/api/graph` request fails or returns empty data.

**Diagnose**:
1. Open browser developer tools (F12)
2. Go to Network tab
3. Find `/api/graph` request
4. Check Status: Should be `200 OK`
5. Check Response: Should contain `{"nodes": [...], "edges": [...]}`

**Solution A - Test API Directly**:
```bash
curl http://10.10.10.135:8000/api/graph
```

**Solution B - Check Server Logs**:
```bash
# Check if server is running
ss -tlnp | grep 8000

# Check process
ps aux | grep viz_server

# If using viz_server_debug.py, it logs to console
# Check terminal where server was started
```

**Solution C - Check Database Connection**:
```bash
# Test Oracle connection
python3 -c "
import oracledb
conn = oracledb.connect(user='openclaw', password='hermes', dsn='10.10.10.130:1521/openclaw')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM MEMORY_NODES')
print('Nodes:', cursor.fetchone()[0])
conn.close()
"
```

### 4. CORS Issues (External Access)
**Problem**: Accessing from different machine fails.

**Symptom**: Browser console shows:
- `Access to fetch at 'http://10.10.10.135:8000/api/graph' from origin 'http://10.10.10.1:8080' has been blocked by CORS policy`

**Solution**: All viz_server versions have CORS enabled. Check code:
```python
def send_cors_headers(self):
    self.send_header('Access-Control-Allow-Origin', '*')
    self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
```

If CORS is blocked, need to check browser extensions or corporate proxy.

## Quick Diagnostic Checklist

**Step 1: Verify Server Running**
```bash
ss -tlnp | grep 8000
# Should show: LISTEN ... python3 ... :8000
```

**Step 2: Test Health Endpoint**
```bash
curl http://10.10.10.135:8000/api/health
# Should return: {"status": "ok", "cache_valid": true, "pool": true}
```

**Step 3: Test Graph API**
```bash
curl http://10.10.10.135:8000/api/graph | python3 -m json.tool
# Should show nodes and edges
```

**Step 4: Check Browser Console**
- Press F12
- Go to Console tab
- Look for red errors
- Look for "vis-network" messages

**Step 5: Check Network Tab**
- Press F12
- Go to Network tab
- Refresh page
- Find vis-network.min.js request
- Check if it failed (red)

## Recommended Server Version

| Scenario | Use This Version |
|----------|-----------------|
| **Production** | `viz_server_single_fixed.py` - No iframe, stable |
| **Development** | `viz_server_debug.py` - With debug panel and multi-CDN |
| **No Internet** | `viz_server_single_fixed.py` with local vis-network.js |
| **Troubleshooting** | `viz_server_debug.py` - Shows CDN load status |

## Common Error Messages

| Error | Meaning | Solution |
|--------|---------|-----------|
| `vis is not defined` | vis-network.js failed to load | Check CDN, use viz_server_debug.py |
| `Failed to load resource` | CDN blocked or unreachable | Check firewall, use alternative CDN |
| `TypeError: vis is undefined` | Script order wrong | vis-network.js must load before use |
| `Network request failed` | `/api/graph` request failed | Check server health, database connection |
| `CORS policy blocked` | Cross-origin access blocked | Check CORS headers (already enabled) |

## Firewall and Network Issues

**Check if port 8000 is open on server**:
```bash
# On the server (10.10.10.135)
firewall-cmd --list-ports | grep 8000

# If not shown, open it
firewall-cmd --permanent --add-port=8000/tcp
firewall-cmd --reload
```

**Check from client machine**:
```bash
# From your browser's machine
telnet 10.10.10.135 8000
# Should connect if port is reachable
```

## Final Steps

If all checks pass but still not working:

1. **Try different browser** - Chrome, Firefox, Safari, Edge
2. **Clear browser cache** - Ctrl+Shift+Delete
3. **Disable browser extensions** - Ad blockers might block CDN
4. **Incognito/Private mode** - Bypass extensions
5. **Screenshot debug panel** (if using viz_server_debug.py)
6. **Check internet connectivity** from server:
   ```bash
   ping -c 3 unpkg.com
   curl -I https://unpkg.com
   ```

## Reference

- Oracle Database: 10.10.10.130:1521/openclaw
- Web Server: 10.10.10.135:8000
- vis-network CDN: https://unpkg.com/vis-network@latest/dist/vis-network.min.js
- Backup CDN: https://cdnjs.cloudflare.com/ajax/libs/vis-network/2.1.9/vis-network.min.js
