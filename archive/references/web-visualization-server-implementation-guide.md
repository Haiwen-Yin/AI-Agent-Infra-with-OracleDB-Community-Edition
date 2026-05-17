# Web Visualization Server Implementation Guide

## Architecture Overview

The Oracle Memory Web Visualization Server provides a browser-based interface for viewing knowledge graphs and memory content with the following features:

1. **Dual-Page Architecture**: `/graph` and `/memory` routes
2. **Session-Based Authentication**: Cookie-based session management
3. **Bilingual Interface**: Chinese/English support with toggle
4. **Node Detail Display**: Click-to-view node information
5. **Performance Optimization**: oracledb driver with connection pooling

## Required Features Checklist

When modifying or restoring the web server, verify ALL of these features:

- [ ] Login page with bilingual labels (用户名 / Username, 密码 / Password, 登录 / Login)
- [ ] Session management with cookie-based authentication
- [ ] `/graph` route showing knowledge nodes
- [ ] `/memory` route showing memory nodes
- [ ] Navigation buttons to switch between pages
- [ ] Node click showing details in sidebar (ID, Type, Label)
- [ ] Logout functionality clearing session
- [ ] oracledb driver for database queries
- [ ] Connection pooling (min=2, max=5)
- [ ] Data caching at startup

## File Structure

```
viz_server_local_js.py
├── Imports (json, http.server, oracledb, etc.)
├── Config (PORT, HOST, DB_*)
├── Session Management (_sessions, create_session, validate_session)
├── Authentication (AUTH_USERS, authenticate)
├── Login Page HTML (LOGIN_HTML)
├── Database Connection Pool (_pool, init_connection_pool)
├── Data Loading (load_graph_data, _graph_cache)
├── HTTP Handler Class (GraphAPIHandler)
│   ├── do_GET (routes: /login, /graph, /memory, /api/*)
│   ├── do_POST (routes: /api/login)
│   ├── check_auth (session validation)
│   ├── redirect (302 response)
│   ├── send_html (main page)
│   ├── send_graph_page (graph/memory pages)
│   ├── send_graph_data (JSON API)
│   ├── send_json_response (helper)
│   └── send_404, send_health, send_stats
└── main() function
```

## Key Implementation Patterns

### 1. Login Page with Bilingual Labels

```python
LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>登录 - Login</title>
    ...
</head>
<body>
    <div class="login-container">
        <h1>🧠 Oracle Memory System</h1>
        <form id="loginForm">
            <div class="form-group">
                <label>用户名 / Username</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>密码 / Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">登录 / Login</button>
        </form>
        <div id="error" class="error"></div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: new URLSearchParams(formData)
            });
            if (response.ok) {
                window.location.href = '/';
            } else {
                const data = await response.json();
                document.getElementById('error').textContent = data.error;
            }
        });
    </script>
</body>
</html>"""
```

### 2. Graph/Memory Page Separation

```python
def send_graph_page(self, mode='graph'):
    """Send graph or memory visualization page"""
    mode_title = 'Knowledge Graph' if mode == 'graph' else 'Memory Content'
    mode_chinese = '知识图谱' if mode == 'graph' else '记忆内容'
    btn_graph_active = 'active' if mode == 'graph' else ''
    btn_memory_active = 'active' if mode == 'memory' else ''
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Oracle Memory System - {mode_title}</title>
    <script src="vis-network.min.js"></script>
    ...
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <h2>🧠 {mode_title}</h2>
            <p>{mode_chinese}</p>
            <div class="nav-buttons">
                <button class="nav-btn {btn_graph_active}" onclick="window.location.href='/graph'">知识图谱</button>
                <button class="nav-btn {btn_memory_active}" onclick="window.location.href='/memory'">记忆内容</button>
            </div>
            <div class="node-info" id="node-info">
                <h3>节点详情 / Node Details</h3>
                <ul>
                    <li><label>ID:</label> <span id="node-id">-</span></li>
                    <li><label>类型 / Type:</label> <span id="node-type">-</span></li>
                    <li><label>名称 / Label:</label> <span id="node-label">-</span></li>
                </ul>
            </div>
            <button class="logout-btn" onclick="window.location.href='/api/logout'">退出登录 / Logout</button>
        </div>
        <div class="main-content">
            <div id="graph-container"></div>
        </div>
    </div>
    <script>
        fetch('/api/graph')
            .then(response => response.json())
            .then(data => {{
                // Filter based on mode
                if ('{mode}' === 'graph') {{
                    data.nodes = data.nodes.filter(n => n.group !== 'memory');
                }} else if ('{mode}' === 'memory') {{
                    data.nodes = data.nodes.filter(n => n.group === 'memory');
                }}
                
                // Create vis-network
                const nodes = new vis.DataSet(data.nodes);
                const edges = new vis.DataSet(data.edges);
                const network = new vis.Network(container, {{ nodes, edges }}, {{...}});
                
                // Click handler for node details
                network.on('click', function(params) {{
                    if (params.nodes.length > 0) {{
                        const node = nodes.get(params.nodes[0]);
                        document.getElementById('node-id').textContent = node.id;
                        document.getElementById('node-type').textContent = node.group;
                        document.getElementById('node-label').textContent = node.label;
                        document.getElementById('node-info').style.display = 'block';
                    }}
                }});
            }});
    </script>
</body>
</html>"""
```

### 3. Session-Based Authentication

```python
_sessions = {}
_SESSION_TIMEOUT = 3600

AUTH_USERS = {
    'admin': 'admin123'
}

def create_session(username):
    token = hashlib.sha256(str(random.random()).encode()).hexdigest()[:32]
    _sessions[token] = {'username': username, 'created': time_module.time()}
    return token

def validate_session(token):
    if token not in _sessions:
        return None
    session = _sessions[token]
    if time_module.time() - session['created'] > _SESSION_TIMEOUT:
        del _sessions[token]
        return None
    return session['username']

def check_auth(self):
    cookie_header = self.headers.get('Cookie', '')
    for cookie in cookie_header.split(';'):
        if cookie.strip().startswith('session='):
            token = cookie.strip()[8:]
            return validate_session(token) is not None
    return False
```

### 4. HTTP Handler Routes

```python
def do_GET(self):
    path = urlparse(self.path).path
    
    # Public routes
    if path == '/login':
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(LOGIN_HTML.encode('utf-8'))
        return
    
    if path == '/api/health':
        self.send_health()
        return
    
    # Protected routes
    if not self.check_auth():
        self.redirect('/login')
        return
    
    if path in ('/', '/index.html'):
        self.send_html()
    elif path == '/graph':
        self.send_graph_page(mode='graph')
    elif path == '/memory':
        self.send_graph_page(mode='memory')
    elif path == '/api/graph':
        self.send_graph_data()
    elif path == '/api/logout':
        self.send_response(302)
        self.send_header('Set-Cookie', 'session=; Path=/; Max-Age=0')
        self.send_header('Location', '/login')
        self.end_headers()
    else:
        self.send_404()
```

## Restoration from Package

### Step 1: Restore Original File

```bash
# From v1.1.0 package
unzip -q -o /tmp/oracle-memory-by-yhw-v1.1.0.zip oracle-memory-by-yhw/viz_server_optimized.py -d /root/.hermes/skills/oracle-memory-by-yhw/
cp /root/.hermes/skills/oracle-memory-by-yhw/viz_server_optimized.py /root/.hermes/skills/oracle-memory-by-yhw/viz_server_local_js.py
```

### Step 2: Add Session Management

Insert after imports:
- `_sessions` dictionary
- `create_session()`, `validate_session()`, `authenticate()` functions
- `LOGIN_HTML` variable with bilingual form

### Step 3: Modify HTTP Handler

Replace `do_GET` method with:
- Login route (public)
- Health check route (public)
- Protected routes with authentication check
- Graph/memory page routes

Add new methods:
- `do_POST` for login handling
- `check_auth` for session validation
- `redirect` for 302 responses
- `send_graph_page` for dual-page architecture

### Step 4: Verify Features

```bash
# Test all endpoints
curl -s http://localhost:8000/login | grep "用户名 / Username"
curl -s -c /tmp/cookies.txt -X POST -d "username=admin&password=admin123" http://localhost:8000/api/login
curl -s -b /tmp/cookies.txt http://localhost:8000/graph | grep "知识图谱"
curl -s -b /tmp/cookies.txt http://localhost:8000/memory | grep "记忆内容"
```

## Related Files

- [Web Server Restoration Session 2026-05-12](web-server-restoration-session-2026-05-12.md) - Session notes with user feedback and pitfalls
- [Oracle Memory Server Restoration](../../oracle-memory-web-server-performance-optimization/references/oracle-memory-server-restoration-2026-05-12.md) - Original restoration session

---

**Author**: Haiwen Yin (胖头鱼 🐟 / yhw)
