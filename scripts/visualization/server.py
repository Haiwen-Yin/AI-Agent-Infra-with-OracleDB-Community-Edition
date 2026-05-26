"""Oracle Memory System v2.3.1 - Web Visualization Server

Lightweight HTTP server providing session-based auth, page routing,
and JSON API endpoints for knowledge, memory, agents, tasks, workspaces,
specs, collaboration groups, and graph visualization.
"""

import hashlib
import json
import os
import sys
import time
import urllib.parse
from decimal import Decimal
from http.cookies import SimpleCookie
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib import connection, memory_api, knowledge_api, agent_api
from lib import task_plan_api, workspace_api, harness_api, graph_api
from lib import spec_api, collab_api
from lib import security, config

VERSION = "2.3.1"

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

sessions = {}

PAGE_ROUTES = {
    '/knowledge': 'knowledge.html',
    '/memory': 'memory.html',
    '/agents': 'agents.html',
    '/tasks': 'tasks.html',
    '/workspaces': 'workspaces.html',
    '/graph': 'graph.html',
    '/specs': 'specs.html',
    '/collab': 'collab.html',
}

PUBLIC_API = {'/api/health', '/api/login'}


def _load_server_config():
    cfg = config.get_config()
    return cfg.server


def _create_session(username, user_id, role):
    raw = "{}:{}:{}:{}".format(username, user_id, role, time.time())
    session_id = hashlib.sha256(raw.encode()).hexdigest()
    sessions[session_id] = {
        'username': username,
        'user_id': user_id,
        'role': role,
        'created_at': time.time(),
    }
    return session_id


def _get_session(request_handler):
    cookie = SimpleCookie(request_handler.headers.get('Cookie', ''))
    session_id = None
    if 'session_id' in cookie:
        session_id = cookie['session_id'].value
    if not session_id:
        return None
    sess = sessions.get(session_id)
    if not sess:
        return None
    cfg = _load_server_config()
    timeout = getattr(cfg, 'session_timeout', 300) * 60
    if time.time() - sess['created_at'] > timeout:
        sessions.pop(session_id, None)
        return None
    return session_id, sess


def _authenticate(username, password):
    try:
        row = connection.execute_query_one(
            "SELECT user_id, username, password_hash, role, status FROM system_users WHERE username = :1",
            (username,)
        )
    except Exception:
        return None
    if not row or row.get('status') != 'ACTIVE':
        return None
    stored_hash = row.get('password_hash', '')
    if stored_hash and stored_hash.startswith('SHA256:'):
        expected = stored_hash[7:]
        actual = hashlib.sha256(password.encode()).hexdigest()
        if actual == expected:
            return row
    return None


def _serialize_datetime(val):
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def _clean_row(row):
    if not isinstance(row, dict):
        return row
    out = {}
    for k, v in row.items():
        if hasattr(v, 'isoformat'):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = int(v) if v % 1 == 0 else float(v)
        elif isinstance(v, bytes):
            try:
                out[k] = v.decode('utf-8')
            except Exception:
                out[k] = v.hex()
        else:
            out[k] = v
    return out


def _graph_all():
    all_items = graph_api.graph_search(keyword=None, limit=200)
    all_edges = connection.execute_query(
        "SELECT source_id, target_id, edge_type, strength FROM entity_edges"
    )
    type_colors = {
            'KNOWLEDGE': '#4a90d9', 'MEMORY': '#4fc3f7', 'TASK_OUTPUT': '#ffb74d',
            'EXPERIENCE': '#e57373', 'HARNESS_TEMPLATE': '#ba68c8', 'SPEC': '#66bb6a',
        }
    nodes = []
    for item in all_items:
        tc = type_colors.get(item.get('entity_type', ''), '#666')
        imp = item.get('importance', 5)
        nodes.append({
            'id': item['entity_id'],
            'label': (item.get('title') or '')[:40],
            'title': item.get('title') or '',
            'entity_type': item.get('entity_type', ''),
            'importance': imp,
            'color': {'background': tc, 'border': tc},
            'size': 5 + (imp / 10) * 15,
            'category': item.get('category') or '',
        })
    edges = []
    for e in all_edges:
        edges.append({
            'from': e['source_id'],
            'to': e['target_id'],
            'label': e.get('edge_type', ''),
        })
    return {'nodes': nodes, 'edges': edges}


def _get_tags_for_entities(entity_ids):
    if not entity_ids:
        return {}
    tags_map = {}
    rows = connection.execute_query(
        "SELECT et.entity_id, t.tag_name FROM entity_tags et JOIN tags t ON et.tag_id = t.tag_id "
        "WHERE et.entity_id IN (%s)"
        % ','.join(["'%s'" % eid for eid in entity_ids])
    )
    for r in rows:
        eid = r['entity_id']
        if eid not in tags_map:
            tags_map[eid] = []
        tags_map[eid].append(r['tag_name'])
    return tags_map


def _knowledge_to_vis():
    items = knowledge_api.search_knowledge(limit=500)
    edges = connection.execute_query(
        "SELECT source_id, source_type, target_id, edge_type, strength, confidence FROM entity_edges "
        "WHERE source_type = 'KNOWLEDGE' OR target_id IN (%s)" % ','.join(["'%s'" % i['entity_id'] for i in items]) if items else "FALSE",
    ) if items else []
    eids = [i['entity_id'] for i in items]
    tags_map = _get_tags_for_entities(eids)
    nodes = []
    for item in items:
        nodes.append({
            'id': item['entity_id'],
            'label': (item.get('title') or '')[:60],
            'group': item.get('domain') or item.get('category') or 'general',
            'title': item.get('summary') or item.get('title') or '',
            'entity_type': 'KNOWLEDGE',
            'importance': item.get('importance', 5),
            'content': item.get('content') or '',
            'summary': item.get('summary') or '',
            'domain': item.get('domain') or '',
            'topic': item.get('topic') or '',
            'difficulty': item.get('difficulty') or '',
            'review_count': item.get('review_count', 0),
            'tags': tags_map.get(item['entity_id'], []),
        })
    vis_edges = []
    for e in edges:
        vis_edges.append({
            'from': e['source_id'],
            'to': e['target_id'],
            'label': e.get('edge_type', ''),
            'value': float(e.get('strength', 1.0)),
        })
    return {'nodes': nodes, 'edges': vis_edges}


def _memory_to_vis():
    items = memory_api.search_memories(limit=500)
    eids = [i['entity_id'] for i in items]
    tags_map = _get_tags_for_entities(eids)
    mem_edges = connection.execute_query(
        "SELECT source_id, target_id, edge_type, strength FROM entity_edges "
        "WHERE source_type = 'MEMORY' OR target_id IN (%s)"
        % ','.join(["'%s'" % eid for eid in eids]) if eids else "FALSE",
    ) if eids else []
    nodes = []
    for item in items:
        nodes.append({
            'id': item['entity_id'],
            'label': (item.get('title') or '')[:60],
            'group': item.get('category') or 'general',
            'title': item.get('summary') or item.get('title') or '',
            'entity_type': 'MEMORY',
            'importance': item.get('importance', 5),
            'content': item.get('content') or '',
            'summary': item.get('summary') or '',
            'category': item.get('category') or '',
            'visibility': item.get('visibility') or '',
            'owned_by_agent': item.get('owned_by_agent') or '',
            'tags': tags_map.get(item['entity_id'], []),
        })
    vis_edges = []
    for e in mem_edges:
        vis_edges.append({
            'from': e['source_id'],
            'to': e['target_id'],
            'label': e.get('edge_type', ''),
            'value': float(e.get('strength', 1.0)),
        })
    return {'nodes': nodes, 'edges': vis_edges}


class VisHandler(BaseHTTPRequestHandler):
    allow_reuse_address = True

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=_serialize_datetime).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_redirect(self, url):
        self.send_response(302)
        self.send_header('Location', url)
        self.end_headers()

    def _send_error(self, code, message=''):
        self._send_json({'error': message or self.responses.get(code, ('',))[1]}, code)

    def _require_auth(self):
        result = _get_session(self)
        if result is None:
            self._send_error(401, 'Authentication required')
            return None
        return result

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length:
            return self.rfile.read(length)
        return b''

    def do_GET(self):
        try:
            self._do_GET_impl()
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self._send_error(500, str(e))
            except:
                pass

    def _do_GET_impl(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        qs = urllib.parse.parse_qs(parsed.query)

        if path == '/' :
            self._send_redirect('/knowledge')
            return

        if path == '/login':
            self._serve_template('login.html')
            return

        if path == '/logout':
            session_data = _get_session(self)
            if session_data:
                sessions.pop(session_data[0], None)
            self.send_response(302)
            self.send_header('Location', '/login')
            self.send_header('Set-Cookie', 'session_id=; Path=/; Max-Age=0')
            self.end_headers()
            return

        if path in PAGE_ROUTES:
            if _get_session(self) is None:
                self._send_redirect('/login')
                return
            self._serve_template(PAGE_ROUTES[path])
            return

        if path.startswith('/api/'):
            self._handle_api_get(path, qs)
            return

        if path.startswith('/static/'):
            self._serve_static(path[8:])
            return

        self._send_error(404, 'Not found')

    def do_POST(self):
        try:
            self._do_POST_impl()
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self._send_error(500, str(e))
            except:
                pass

    def _do_POST_impl(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'

        if path == '/api/login':
            self._handle_login()
            return

        self._send_error(404, 'Not found')

    def _handle_login(self):
        try:
            body = self._read_body()
            data = json.loads(body)
            username = data.get('username', '')
            password = data.get('password', '')
        except Exception:
            self._send_json({'success': False, 'error': 'Invalid request'}, 400)
            return

        user = _authenticate(username, password)
        if not user:
            self._send_json({'success': False, 'error': 'Invalid credentials'}, 401)
            return

        session_id = _create_session(user['username'], str(user['user_id']), user.get('role', 'user'))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', 'session_id={}; Path=/; HttpOnly'.format(session_id))
        body = json.dumps({'success': True, 'session_id': session_id}).encode()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_api_get(self, path, qs):
        if path not in PUBLIC_API:
            if self._require_auth() is None:
                return

        try:
            if path == '/api/health':
                self._send_json({'status': 'ok', 'version': VERSION})
            elif path == '/api/knowledge':
                self._send_json(_knowledge_to_vis())
            elif path == '/api/memory':
                self._send_json(_memory_to_vis())
            elif path == '/api/agents':
                self._api_agents()
            elif path == '/api/tasks':
                self._api_tasks()
            elif path == '/api/workspaces':
                self._api_workspaces()
            elif path == '/api/specs':
                self._api_specs()
            elif path == '/api/collab':
                self._api_collab()
            elif path == '/api/stats':
                self._api_stats()
            elif path == '/api/graph/neighbors':
                entity_id = qs.get('entity_id', [None])[0]
                if not entity_id:
                    self._send_error(400, 'entity_id required')
                    return
                self._send_json(graph_api.get_neighbors(entity_id))
            elif path == '/api/graph/context':
                entity_id = qs.get('entity_id', [None])[0]
                if not entity_id:
                    self._send_error(400, 'entity_id required')
                    return
                ctx = graph_api.get_entity_context(entity_id)
                if ctx is None:
                    self._send_error(404, 'Entity not found')
                    return
                self._send_json(_clean_row(ctx))
            elif path == '/api/graph/stats':
                self._send_json(graph_api.get_graph_stats())
            elif path == '/api/graph/search':
                q = qs.get('q', [''])[0]
                et = qs.get('type', [None])[0]
                self._send_json(graph_api.graph_search(keyword=q if q else None, entity_type=et))
            elif path == '/api/graph/all':
                self._send_json(_graph_all())
            else:
                self._send_error(404, 'API endpoint not found')
        except Exception as e:
            self._send_error(500, str(e))

    def _api_agents(self):
        agents = connection.execute_query(
            "SELECT agent_id, agent_name, agent_type, description, status, "
            "last_seen_at, created_at, updated_at FROM agent_registry ORDER BY created_at DESC"
        )
        sessions_list = agent_api.get_active_sessions()
        collaborations = connection.execute_query(
            "SELECT col_id, source_agent_id, target_agent_id, col_type, entity_id, "
            "context, strength, created_at FROM agent_collaboration ORDER BY created_at DESC"
        )
        self._send_json({
            'agents': [_clean_row(a) for a in agents],
            'sessions': [_clean_row(s) for s in sessions_list],
            'collaborations': [_clean_row(c) for c in collaborations],
        })

    def _api_tasks(self):
        plans = task_plan_api.list_plans(limit=100)
        for plan in plans:
            plan['steps'] = task_plan_api.get_plan_steps(plan['plan_id'])
        self._send_json({'plans': [_clean_row(p) for p in plans]})

    def _api_workspaces(self):
        workspaces = connection.execute_query(
            "SELECT workspace_id, owner_user_id, workspace_name, workspace_type, "
            "isolation_mode, current_agent_id, current_session_id, summary, status, "
            "created_at, updated_at FROM workspaces ORDER BY updated_at DESC"
        )
        for ws in workspaces:
            ctx_count = connection.execute_query_one(
                "SELECT COUNT(*) AS cnt FROM workspace_context WHERE workspace_id = :1",
                (ws['workspace_id'],)
            )
            ws['context_count'] = ctx_count['cnt'] if ctx_count else 0
            ctx_chain = connection.execute_query(
                "SELECT context_id, context_type, agent_id, context_data, parent_context_id, created_at "
                "FROM workspace_context WHERE workspace_id = :1 ORDER BY created_at DESC",
                (ws['workspace_id'],)
            )
            ws['context_chain'] = [_clean_row(c) for c in ctx_chain]
            linked = connection.execute_query(
                "SELECT wt.plan_id, tp.goal, tp.status FROM workspace_tasks wt "
                "JOIN task_plans tp ON wt.plan_id = tp.plan_id "
                "WHERE wt.workspace_id = :1",
                (ws['workspace_id'],)
            )
            ws['linked_tasks'] = [_clean_row(t) for t in linked]
            ws['task_count'] = len(linked)
        self._send_json({'workspaces': [_clean_row(w) for w in workspaces]})

    def _api_specs(self):
        specs = spec_api.list_specs(limit=100)
        for sp in specs:
            sp['plan_links'] = spec_api.get_spec_plan_links(sp['entity_id'])
        self._send_json({'specs': [_clean_row(s) for s in specs]})

    def _api_collab(self):
        groups = connection.execute_query(
            "SELECT g.group_id, g.group_name, g.group_type, g.description, "
            "g.workspace_id, g.coordinator_agent_id, g.sharing_policy, g.status, "
            "g.metadata, g.created_at, g.updated_at, "
            "(SELECT COUNT(*) FROM collab_group_members cgm WHERE cgm.group_id = g.group_id AND cgm.status = 'ACTIVE') AS member_count "
            "FROM collab_groups g ORDER BY g.updated_at DESC"
        )
        for g in groups:
            members = connection.execute_query(
                "SELECT member_id, agent_id, role, personal_workspace_id, joined_at, status "
                "FROM collab_group_members WHERE group_id = :1 ORDER BY joined_at",
                (g['group_id'],)
            )
            g['members'] = [_clean_row(m) for m in members]
        self._send_json({'groups': [_clean_row(g) for g in groups]})

    def _api_stats(self):
        entity_counts = {}
        type_rows = connection.execute_query(
            "SELECT entity_type, COUNT(*) AS cnt FROM entities GROUP BY entity_type"
        )
        for r in type_rows:
            entity_counts[r['entity_type']] = r['cnt']
        edge_row = connection.execute_query_one("SELECT COUNT(*) AS cnt FROM entity_edges")
        ws_row = connection.execute_query_one("SELECT COUNT(*) AS cnt FROM workspaces")
        agent_row = connection.execute_query_one("SELECT COUNT(*) AS cnt FROM agent_registry")
        spec_row = connection.execute_query_one("SELECT COUNT(*) AS cnt FROM entities WHERE entity_type = 'SPEC'")
        collab_row = connection.execute_query_one("SELECT COUNT(*) AS cnt FROM collab_groups")
        self._send_json({
            'entity_counts': entity_counts,
            'edge_count': edge_row['cnt'] if edge_row else 0,
            'workspace_count': ws_row['cnt'] if ws_row else 0,
            'agent_count': agent_row['cnt'] if agent_row else 0,
            'spec_count': spec_row['cnt'] if spec_row else 0,
            'collab_count': collab_row['cnt'] if collab_row else 0,
        })

    def _serve_template(self, filename):
        filepath = os.path.join(TEMPLATES_DIR, filename)
        if not os.path.isfile(filepath):
            self._send_error(404, 'Template not found')
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                html = f.read()
            html = html.replace('{{VERSION}}', VERSION)
            self._send_html(html)
        except Exception as e:
            self._send_error(500, str(e))

    def _serve_static(self, filepath):
        full = os.path.join(STATIC_DIR, filepath)
        if not os.path.isfile(full):
            self._send_error(404, 'File not found')
            return
        try:
            with open(full, 'rb') as f:
                data = f.read()
            ext = os.path.splitext(full)[1].lower()
            ct = {'.css': 'text/css', '.js': 'application/javascript',
                  '.png': 'image/png', '.jpg': 'image/jpeg',
                  '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}.get(ext, 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_error(500, str(e))


def main():
    cfg = _load_server_config()
    host = getattr(cfg, 'host', '0.0.0.0')
    port = getattr(cfg, 'port', 8000)

    try:
        connection.get_pool()
        print("[server] Database connection pool initialized")
    except Exception as e:
        print("[server] WARNING: Database connection failed: {}".format(e))

    server = HTTPServer((host, port), VisHandler)
    print("[server] Oracle Memory System v{} visualization server".format(VERSION))
    print("[server] Listening on http://{}:{}".format(host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] Shutting down")
        server.server_close()
        connection.close_pool()


if __name__ == '__main__':
    main()
