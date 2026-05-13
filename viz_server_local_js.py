#!/usr/bin/env python3
"""
Oracle Memory System - Complete Web Visualization Server
Author: Haiwen (胖头鱼 🐟) | Version: v1.1.0
Features: Login auth, bilingual, graph/memory pages, language toggle, node details
"""

import json
import http.server
import socketserver
import oracledb
import threading
import random
import hashlib
import time as time_module
import os
from datetime import datetime
from urllib.parse import urlparse

# ============================================================================
# Config - Load from config.json with environment variable overrides
# ============================================================================

def load_config():
    """Load configuration from config.json with environment variable overrides"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    
    # Default config
    config = {
        "server": {"host": "0.0.0.0", "port": 8000},
        "database": {"user": "openclaw", "password": "hermes", "dsn": "10.10.10.130:1521/openclaw"},
        "session": {"timeout": 300}
    }
    
    # Load from file if exists
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f'Warning: Failed to load config.json: {e}')
    
    # Environment variable overrides
    if os.environ.get('MEMORY_DB_USER'):
        config['database']['user'] = os.environ['MEMORY_DB_USER']
    if os.environ.get('MEMORY_DB_PASSWORD'):
        config['database']['password'] = os.environ['MEMORY_DB_PASSWORD']
    if os.environ.get('MEMORY_DB_DSN'):
        config['database']['dsn'] = os.environ['MEMORY_DB_DSN']
    if os.environ.get('MEMORY_SERVER_PORT'):
        config['server']['port'] = int(os.environ['MEMORY_SERVER_PORT'])
    if os.environ.get('MEMORY_SERVER_HOST'):
        config['server']['host'] = os.environ['MEMORY_SERVER_HOST']
    if os.environ.get('MEMORY_SESSION_TIMEOUT'):
        config['session']['timeout'] = int(os.environ['MEMORY_SESSION_TIMEOUT'])
    
    return config

# Load configuration
_config = load_config()

# Extract values for easy access
PORT = _config['server']['port']
HOST = _config['server']['host']
DB_USER = _config['database']['user']
DB_PASSWORD = _config['database']['password']
DB_DSN = _config['database']['dsn']
_SESSION_TIMEOUT = _config['session']['timeout']

# ============================================================================
# Session Management & Authentication
# ============================================================================

_sessions = {}

def generate_session_token():
    return hashlib.sha256(str(random.random()).encode()).hexdigest()[:32]

def create_session(username):
    token = generate_session_token()
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

def authenticate(username, password):
    """Authenticate user against database with PBKDF2 hashing"""
    conn = None
    try:
        conn = oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT password_hash, salt, is_active, locked_until
            FROM memory_system_users 
            WHERE username = :1
        ''', [username])
        
        row = cursor.fetchone()
        if not row:
            return False
        
        stored_hash, salt_hex, is_active, locked_until = row
        
        # Check if account is locked
        if locked_until:
            from datetime import datetime
            if datetime.now() < locked_until:
                return False
        
        # Check if account is active
        if not is_active:
            return False
        
        # Verify password with PBKDF2
        salt = bytes.fromhex(salt_hex)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        
        if password_hash.hex() == stored_hash:
            # Reset login attempts and update last login
            cursor.execute('''
                UPDATE memory_system_users 
                SET login_attempts = 0, last_login = SYSTIMESTAMP, locked_until = NULL
                WHERE username = :1
            ''', [username])
            conn.commit()
            return True
        else:
            # Increment login attempts
            cursor.execute('''
                UPDATE memory_system_users 
                SET login_attempts = login_attempts + 1
                WHERE username = :1
            ''', [username])
            
            # Lock account after 5 failed attempts
            cursor.execute('''
                UPDATE memory_system_users 
                SET locked_until = SYSTIMESTAMP + INTERVAL '15' MINUTE
                WHERE username = :1 AND login_attempts >= 5
            ''', [username])
            conn.commit()
            return False
            
    except Exception as e:
        print(f'Auth error: {e}')
        return False
    finally:
        if conn:
            conn.close()

# ============================================================================
# Login Page HTML (Bilingual)
# ============================================================================

LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登录 - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
        }
        .login-container {
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(10px);
            padding: 40px; border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%; max-width: 400px;
        }
        h1 { color: white; text-align: center; margin-bottom: 30px; font-size: 24px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; color: white; margin-bottom: 8px; font-weight: bold; }
        input {
            width: 100%; padding: 12px; border: none; border-radius: 8px;
            font-size: 16px; background: rgba(255,255,255,0.9);
        }
        input:focus { outline: 2px solid #667eea; }
        button {
            width: 100%; padding: 14px; background: #667eea; color: white;
            border: none; border-radius: 8px; font-size: 16px; font-weight: bold;
            cursor: pointer; transition: background 0.3s;
        }
        button:hover { background: #5568d3; }
        .error { color: #ff6b6b; text-align: center; margin-top: 15px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>🧠 Oracle Memory System</h1>
        <form id="loginForm">
            <div class="form-group">
                <label>用户名 / Username</label>
                <input type="text" name="username" required placeholder="admin">
            </div>
            <div class="form-group">
                <label>密码 / Password</label>
                <input type="password" name="password" required placeholder="••••••••">
            </div>
            <button type="submit">登录 / Login</button>
        </form>
        <div id="error" class="error"></div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const errorDiv = document.getElementById('error');
            try {
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: new URLSearchParams(formData)
                });
                if (response.ok) {
                    window.location.href = '/knowledge';
                } else {
                    const data = await response.json();
                    errorDiv.textContent = data.error || '登录失败 / Login failed';
                }
            } catch (error) {
                errorDiv.textContent = '网络错误 / Network error';
            }
        });
    </script>
</body>
</html>"""

# ============================================================================
# Graph/Memory Page HTML Template
# ============================================================================

def build_page_html(mode='graph'):
    """Build the graph or memory page with all features"""
    is_knowledge = mode in ('graph', 'knowledge')
    mode_title = 'Knowledge Graph' if is_knowledge else 'Memory Content'
    mode_chinese = '知识图谱' if is_knowledge else '记忆内容'
    btn_graph_active = 'active' if mode == 'graph' else ''
    btn_memory_active = 'active' if mode == 'memory' else ''

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Oracle Memory System - {mode_title}</title>
    <script src="vis-network.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{ display: flex; height: 100vh; }}
        .sidebar {{
            width: 300px;
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            padding: 20px;
            color: white;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }}
        .sidebar h2 {{
            margin-bottom: 20px;
            font-size: 22px;
            border-bottom: 2px solid rgba(255,255,255,0.3);
            padding-bottom: 10px;
        }}
        .sidebar p {{ margin-bottom: 8px; font-size: 13px; line-height: 1.6; }}
        .main-content {{ flex: 1; padding: 15px; }}
        #graph-container {{
            width: 100%; height: 100%;
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        .loading {{
            display: flex; flex-direction: column; align-items: center;
            justify-content: center; height: 100%; color: white;
        }}
        .spinner {{
            width: 50px; height: 50px; border: 5px solid rgba(255,255,255,0.3);
            border-top-color: white; border-radius: 50%;
            animation: spin 1s linear infinite;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        .section-title {{
            font-weight: bold; font-size: 14px; margin-top: 15px; margin-bottom: 8px;
            border-bottom: 1px solid rgba(255,255,255,0.2); padding-bottom: 5px;
        }}
        .nav-buttons {{ display: flex; gap: 8px; margin-bottom: 10px; }}
        .nav-btn {{
            flex: 1; padding: 8px; background: rgba(255,255,255,0.2);
            color: white; border: none; border-radius: 5px; cursor: pointer;
            font-size: 13px; text-align: center; transition: background 0.2s;
        }}
        .nav-btn:hover {{ background: rgba(255,255,255,0.35); }}
        .nav-btn.active {{ background: rgba(255,255,255,0.5); font-weight: bold; }}
        .lang-buttons {{ display: flex; gap: 8px; }}
        .lang-btn {{
            flex: 1; padding: 6px; background: rgba(255,255,255,0.2);
            color: white; border: none; border-radius: 5px; cursor: pointer;
            font-size: 12px; text-align: center;
        }}
        .lang-btn.active {{ background: rgba(255,255,255,0.5); font-weight: bold; }}
        .node-info {{
            margin-top: 15px; padding: 12px;
            background: rgba(255,255,255,0.15);
            border-radius: 8px; display: none;
        }}
        .node-info.active {{ display: block; }}
        .node-info h3 {{ margin-bottom: 8px; font-size: 14px; }}
        .node-info p {{ font-size: 13px; margin-bottom: 4px; }}
        .node-info label {{ font-weight: bold; }}
        .logout-btn {{
            margin-top: auto; padding: 10px;
            background: rgba(255,0,0,0.3);
            color: white; border: none; border-radius: 5px;
            cursor: pointer; font-size: 13px;
        }}
        .logout-btn:hover {{ background: rgba(255,0,0,0.5); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <h2 id="sidebar-title"></h2>
            <p><strong>Oracle Memory System</strong></p>

            <div class="section-title" id="lbl-instructions"></div>
            <p id="p-drag"></p>
            <p id="p-scroll"></p>
            <p id="p-click"></p>

            <div class="section-title" id="lbl-pages"></div>
            <div class="nav-buttons">
                <button class="nav-btn" id="btn-graph"></button>
                <button class="nav-btn" id="btn-memory"></button>
            </div>

            <div class="section-title" id="lbl-lang"></div>
            <div class="lang-buttons">
                <button class="lang-btn" id="btn-zh" onclick="toggleLang('zh')">中文</button>
                <button class="lang-btn" id="btn-en" onclick="toggleLang('en')">English</button>
            </div>

            <div class="node-info" id="node-info">
                <h3 id="lbl-details"></h3>
                <p><label>ID:</label> <span id="node-id">-</span></p>
                <p id="p-type"><label></label> <span id="node-type">-</span></p>
                <p id="p-label"><label></label> <span id="node-label">-</span></p>
            </div>

            <button class="logout-btn" id="btn-logout"></button>
        </div>
        <div class="main-content">
            <div id="loading" class="loading">
                <div class="spinner"></div>
                <p id="loading-text"></p>
            </div>
            <div id="graph-container" style="display:none;"></div>
        </div>
    </div>
    <script>
        // Pure Chinese / Pure English — no bilingual mixing
        const i18n = {{
            zh: {{
                title_zh: '知识图谱', title_en: '记忆内容',
                instructions: '操作指南',
                drag: '拖拽：移动节点', scroll: '滚轮：缩放视图', click: '点击：查看详情',
                graphBtn: '知识图谱', memoryBtn: '记忆内容',
                pages: '页面切换',
                details: '节点详情', type: '类型:', label: '名称:',
                logout: '退出登录', loading: '正在加载数据...',
                lang: '语言'
            }},
            en: {{
                title_zh: 'Knowledge Graph', title_en: 'Memory Content',
                instructions: 'Instructions',
                drag: 'Drag: Move nodes', scroll: 'Scroll: Zoom', click: 'Click: View details',
                graphBtn: 'Knowledge', memoryBtn: 'Memory',
                pages: 'Pages',
                details: 'Node Details', type: 'Type:', label: 'Label:',
                logout: 'Logout', loading: 'Loading data...',
                lang: 'Language'
            }}
        }};

        const mode = '{mode}';
        function getLang() {{ return localStorage.getItem('lang') || 'zh'; }}

        function toggleLang(lang) {{
            localStorage.setItem('lang', lang);
            applyLang(lang);
        }}

        function applyLang(lang) {{
            const t = i18n[lang];
            document.getElementById('sidebar-title').textContent = '🧠 ' + (mode !== 'memory' ? t.title_zh : t.title_en);
            document.getElementById('lbl-instructions').textContent = t.instructions;
            document.getElementById('p-drag').textContent = t.drag;
            document.getElementById('p-scroll').textContent = t.scroll;
            document.getElementById('p-click').textContent = t.click;
            document.getElementById('btn-graph').textContent = t.graphBtn;
            document.getElementById('btn-memory').textContent = t.memoryBtn;
            document.getElementById('lbl-pages').textContent = t.pages;
            document.getElementById('lbl-details').textContent = t.details;
            document.getElementById('p-type').querySelector('label').textContent = t.type;
            document.getElementById('p-label').querySelector('label').textContent = t.label;
            document.getElementById('btn-logout').textContent = t.logout;
            document.getElementById('loading-text').textContent = t.loading;
            document.getElementById('lbl-lang').textContent = t.lang;
            // Highlight active language button
            document.getElementById('btn-zh').className = 'lang-btn' + (lang === 'zh' ? ' active' : '');
            document.getElementById('btn-en').className = 'lang-btn' + (lang === 'en' ? ' active' : '');
            // Highlight active page button
            document.getElementById('btn-graph').className = 'nav-btn' + (mode !== 'memory' ? ' active' : '');
            document.getElementById('btn-memory').className = 'nav-btn' + (mode === 'memory' ? ' active' : '');
            document.title = 'Oracle Memory System - ' + (mode !== 'memory' ? t.title_zh : t.title_en);
        }}

        // Set up nav button click handlers (preserve current language)
        document.getElementById('btn-graph').onclick = function() {{ window.location.href = '/knowledge'; }};
        document.getElementById('btn-memory').onclick = function() {{ window.location.href = '/memory'; }};
        document.getElementById('btn-logout').onclick = function() {{ window.location.href = '/api/logout'; }};

        // Apply saved language on page load
        applyLang(getLang());

        // Load data based on page type
        const apiUrl = mode === 'memory' ? '/api/memory' : '/api/knowledge';
        fetch(apiUrl)
            .then(r => r.json())
            .then(data => {{
                const container = document.getElementById('graph-container');
                const loading = document.getElementById('loading');

                // Both pages show all nodes — no filtering

                // Create vis-network
                const nodes = new vis.DataSet(data.nodes);
                const edges = new vis.DataSet(data.edges);

                const network = new vis.Network(container, {{ nodes: nodes, edges: edges }}, {{
                    physics: {{ enabled: true, stabilization: {{ iterations: 100 }} }},
                    interaction: {{ hover: true }},
                    nodes: {{ shape: 'dot', font: {{ color: '#000000', size: 12 }}, borderWidth: 2 }},
                    edges: {{ width: 1.5, smooth: true, arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }} }}
                }});

                loading.style.display = 'none';
                container.style.display = 'block';

                // Click handler for node details
                network.on('click', function(params) {{
                    if (params.nodes.length > 0) {{
                        const nodeId = params.nodes[0];
                        const node = nodes.get(nodeId);
                        document.getElementById('node-id').textContent = node.id;
                        document.getElementById('node-type').textContent = node.group || 'unknown';
                        document.getElementById('node-label').textContent = node.label;
                        document.getElementById('node-info').classList.add('active');
                    }}
                }});
            }})
            .catch(error => {{
                console.error('Error:', error);
                document.getElementById('loading').innerHTML = '<p style="color:white">加载失败 / Load failed</p>';
            }});
    </script>
</body>
</html>"""

# ============================================================================
# Database Connection Pool
# ============================================================================

_pool = None
_connection_lock = threading.Lock()

def init_connection_pool():
    global _pool
    if _pool is None:
        with _connection_lock:
            if _pool is None:
                print("🔌 Initializing database connection pool...")
                _pool = oracledb.create_pool(
                    user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN,
                    min=2, max=5, increment=1,
                    getmode=oracledb.SPOOL_ATTRVAL_NOWAIT
                )
                print("✅ Connection pool created (min=2, max=5)")

def get_connection():
    if _pool is None:
        init_connection_pool()
    return _pool.acquire()

def release_connection(conn):
    if _pool:
        _pool.release(conn)

# ============================================================================
# Graph Data Cache (Knowledge & Memory separately)
# ============================================================================

_knowledge_cache = {'data': None, 'timestamp': None, 'ttl': 300}
_memory_cache = {'data': None, 'timestamp': None, 'ttl': 300}
_cache_lock = threading.Lock()

def get_node_color(node_type):
    if not node_type:
        return '#95a5a6'
    colors = {
        'CONCEPT': '#e74c3c', 'ENTITY': '#3498db', 'RELATION': '#2ecc71',
        'ATTRIBUTE': '#f39c12', 'TASK': '#9b59b6', 'MEMORY': '#1abc9c',
        'QUERY': '#34495e', 'SYSTEM': '#e67e22', 'FEATURE': '#27aeae',
        'KNOWLEDGEAREA': '#8e44ad',
    }
    return colors.get(node_type.upper(), '#95a5a6')

def load_knowledge_data():
    """Load knowledge graph from KNOWLEDGE_CONCEPTS table"""
    with _cache_lock:
        now = datetime.now().timestamp()
        if (_knowledge_cache['data'] is not None and
            _knowledge_cache['timestamp'] is not None and
            now - _knowledge_cache['timestamp'] < _knowledge_cache['ttl']):
            print("📦 Using cached knowledge data")
            return _knowledge_cache['data']

        print("📊 Loading knowledge graph from KNOWLEDGE_CONCEPTS...")
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Load knowledge concepts
            cursor.execute("""
                SELECT CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE 
                FROM KNOWLEDGE_CONCEPTS 
                ORDER BY CONCEPT_ID
            """)
            rows = cursor.fetchall()

            nodes = []
            for row in rows:
                cid, cname, ctype = row
                nodes.append({
                    'id': str(cid),
                    'label': str(cname)[:50] if cname else '',
                    'group': str(ctype) if ctype else 'CONCEPT',
                    'color': get_node_color(str(ctype) if ctype else 'CONCEPT'),
                    'title': f"{ctype}: {cname}" if cname else str(ctype)
                })

            print(f"   ✅ Loaded {len(nodes)} knowledge nodes")

            # Load knowledge edges from KNOWLEDGE_GRAPH
            edges = []
            try:
                cursor.execute("""
                    SELECT SOURCE_CONCEPT_ID, TARGET_CONCEPT_ID, RELATION_TYPE 
                    FROM KNOWLEDGE_GRAPH 
                    ORDER BY ROWNUM
                """)
                for row in cursor.fetchall():
                    src, tgt, rtype = row
                    edges.append({
                        'from': str(src), 'to': str(tgt),
                        'label': str(rtype) if rtype else '',
                        'arrows': 'to'
                    })
            except Exception:
                # Fallback: group by type
                type_groups = {}
                for node in nodes:
                    type_groups.setdefault(node['group'], []).append(node['id'])
                for ntype, nids in type_groups.items():
                    for i in range(min(len(nids), 20)):
                        for j in range(i + 1, min(len(nids), i + 3)):
                            edges.append({'from': nids[i], 'to': nids[j], 'label': ntype})

            print(f"   ✅ Created {len(edges)} knowledge edges")

            data = {'nodes': nodes, 'edges': edges}
            _knowledge_cache['data'] = data
            _knowledge_cache['timestamp'] = now
            return data

        except Exception as e:
            print(f"   ❌ Error loading knowledge: {e}")
            return None
        finally:
            if conn:
                release_connection(conn)

def load_memory_data():
    """Load memory graph from MEMORY_NODES + MEMORY_EDGES tables"""
    with _cache_lock:
        now = datetime.now().timestamp()
        if (_memory_cache['data'] is not None and
            _memory_cache['timestamp'] is not None and
            now - _memory_cache['timestamp'] < _memory_cache['ttl']):
            print("📦 Using cached memory data")
            return _memory_cache['data']

        print("📊 Loading memory graph from MEMORY_NODES + MEMORY_EDGES...")
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Load memory nodes
            cursor.execute("""
                SELECT NODE_ID, NODE_TYPE, LABEL 
                FROM MEMORY_NODES 
                ORDER BY NODE_ID
            """)
            rows = cursor.fetchall()

            nodes = []
            for row in rows:
                nid, ntype, nlabel = row
                nodes.append({
                    'id': str(nid),
                    'label': str(nlabel)[:50] if nlabel else '',
                    'group': str(ntype) if ntype else 'UNKNOWN',
                    'color': get_node_color(str(ntype) if ntype else 'UNKNOWN'),
                    'title': f"{ntype}: {nlabel}" if nlabel else str(ntype)
                })

            print(f"   ✅ Loaded {len(nodes)} memory nodes")

            # Load memory edges
            edges = []
            try:
                cursor.execute("""
                    SELECT SOURCE_NODE_ID, TARGET_NODE_ID, EDGE_TYPE 
                    FROM MEMORY_EDGES 
                    ORDER BY EDGE_ID
                """)
                for row in cursor.fetchall():
                    src, tgt, etype = row
                    edges.append({
                        'from': str(src), 'to': str(tgt),
                        'label': str(etype) if etype else '',
                        'arrows': 'to'
                    })
            except Exception:
                # Fallback: group by type
                type_groups = {}
                for node in nodes:
                    type_groups.setdefault(node['group'], []).append(node['id'])
                for ntype, nids in type_groups.items():
                    for i in range(min(len(nids), 20)):
                        for j in range(i + 1, min(len(nids), i + 3)):
                            edges.append({'from': nids[i], 'to': nids[j], 'label': ntype})

            print(f"   ✅ Created {len(edges)} memory edges")

            data = {'nodes': nodes, 'edges': edges}
            _memory_cache['data'] = data
            _memory_cache['timestamp'] = now
            return data

        except Exception as e:
            print(f"   ❌ Error loading memory: {e}")
            return None
        finally:
            if conn:
                release_connection(conn)

def invalidate_cache():
    with _cache_lock:
        _knowledge_cache['data'] = None
        _knowledge_cache['timestamp'] = None
        _memory_cache['data'] = None
        _memory_cache['timestamp'] = None

# ============================================================================
# HTTP Request Handler
# ============================================================================

class GraphAPIHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        # Login page (no auth required)
        if path == '/login':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(LOGIN_HTML.encode('utf-8'))
            return

        # Health check (no auth required)
        if path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'ok',
                'cache_valid': _knowledge_cache['data'] is not None,
                'pool_active': _pool is not None
            }).encode('utf-8'))
            return

        # Static files (no auth required)
        import os
        static_dir = os.path.dirname(os.path.abspath(__file__))
        if path == '/vis-network.min.js':
            filepath = os.path.join(static_dir, 'vis-network.min.js')
            if os.path.isfile(filepath):
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
                return

        # Check authentication for protected routes
        if not self.check_auth():
            self.redirect('/login')
            return

        # Protected routes
        if path in ('/', '/index.html'):
            self.redirect('/knowledge')
        elif path == '/knowledge':
            self.serve_page('knowledge')
        elif path == '/memory':
            self.serve_page('memory')
        elif path == '/api/knowledge':
            self.send_graph_data('knowledge')
        elif path == '/api/knowledge/refresh':
            with _cache_lock:
                _knowledge_cache['data'] = None
                _knowledge_cache['timestamp'] = None
            self.send_graph_data('knowledge')
        elif path == '/api/memory':
            self.send_graph_data('memory')
        elif path == '/api/memory/refresh':
            with _cache_lock:
                _memory_cache['data'] = None
                _memory_cache['timestamp'] = None
            self.send_graph_data('memory')
        elif path == '/api/stats':
            self.send_stats()
        elif path == '/api/logout':
            self.send_response(302)
            self.send_header('Set-Cookie', 'session=; Path=/; Max-Age=0')
            self.send_header('Location', '/login')
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/api/login':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')

            params = {}
            for param in post_data.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = value

            username = params.get('username', '')
            password = params.get('password', '')

            if authenticate(username, password):
                token = create_session(username)
                self.send_response(302)
                self.send_header('Set-Cookie', f'session={token}; Path=/; HttpOnly; SameSite=Strict')
                self.send_header('Location', '/knowledge')
                self.end_headers()
            else:
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': '用户名或密码无效 / Invalid username or password'}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def check_auth(self):
        cookie_header = self.headers.get('Cookie', '')
        session_token = None
        for cookie in cookie_header.split(';'):
            cookie = cookie.strip()
            if cookie.startswith('session='):
                session_token = cookie[8:]
                break
        if not session_token:
            return False
        return validate_session(session_token) is not None

    def redirect(self, path):
        self.send_response(302)
        self.send_header('Location', path)
        self.end_headers()

    def serve_page(self, mode):
        html = build_page_html(mode)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def send_graph_data(self, data_type='knowledge'):
        if data_type == 'memory':
            data = load_memory_data()
        else:
            data = load_knowledge_data()
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_cors_headers()
        self.end_headers()
        if data:
            self.wfile.write(json.dumps(data).encode('utf-8'))
        else:
            self.wfile.write(json.dumps({'nodes': [], 'edges': [], 'error': 'Failed to load data'}).encode('utf-8'))

    def send_stats(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_cors_headers()
        self.end_headers()
        stats = {
            'knowledge_nodes': len(_knowledge_cache['data']['nodes']) if _knowledge_cache['data'] else 0,
            'knowledge_edges': len(_knowledge_cache['data']['edges']) if _knowledge_cache['data'] else 0,
            'memory_nodes': len(_memory_cache['data']['nodes']) if _memory_cache['data'] else 0,
            'memory_edges': len(_memory_cache['data']['edges']) if _memory_cache['data'] else 0,
        }
        self.wfile.write(json.dumps(stats).encode('utf-8'))

# ============================================================================
# Main
# ============================================================================

def main():
    print("\n" + "=" * 70)
    print("         Oracle Memory System - Web Visualization Server v1.1.0")
    print("=" * 70)

    init_connection_pool()
    load_knowledge_data()
    load_memory_data()

    print(f"\n✅ Starting server on http://{HOST}:{PORT}")
    print(f"   Local:   http://localhost:{PORT}")
    print(f"   Network: http://10.10.10.135:{PORT}")
    print(f"   Login:   admin / admin123")
    print(f"   Timeout: {_SESSION_TIMEOUT} seconds")
    print("=" * 70)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((HOST, PORT), GraphAPIHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n🛑 Server stopped")
            if _pool:
                _pool.close()

if __name__ == '__main__':
    main()
