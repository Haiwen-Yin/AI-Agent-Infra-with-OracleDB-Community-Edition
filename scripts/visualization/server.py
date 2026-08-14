"""AI Agent Infra v4.4.4 - Community Edition - Web Visualization Server

Lightweight HTTP server providing session-based auth, page routing,
and JSON API endpoints for knowledge, memory, agents, tasks, workspaces,
specs, collaboration groups, and graph visualization.
"""

import hashlib
import base64
import json
import queue
import threading
import logging
import os
import re
import signal
import socket
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from decimal import Decimal
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib import connection, memory_api, memory_lifecycle, knowledge_api, agent_api
from lib import task_plan_api, workspace_api, harness_api, graph_api
from lib import spec_api, collab_api, branch_api, sdd_api, scm_adapter_api
from lib import security, config, user_api
from lib import loop_api
from lib import message_api, event_bus, trace_api, monitor_api, tool_registry
from lib import edition_features
from lib import agent_registration
from lib import identity_api
from lib import governed_contracts, security_lifecycle
from lib import graph_production_profile
from lib import platform_agent_pool
from lib import native_runtime
if getattr(edition_features, 'GRAPH_ENGINEERING_ENABLED', False):
    from lib import graph_definition_api, graph_compiler, graph_runtime, graph_worker, graph_event_api, graph_adapter, graph_compat, graph_executor
    from lib import graph_assurance, graph_dynamic, a2a_gateway, graph_telemetry
else:
    graph_definition_api = graph_compiler = graph_runtime = graph_worker = graph_event_api = graph_adapter = graph_compat = graph_executor = None
    graph_assurance = graph_dynamic = a2a_gateway = graph_telemetry = None

if edition_features.has_feature('orchestrator'):
    from lib import orchestrator
else:
    orchestrator = None

if edition_features.has_feature('governance'):
    from lib import governance_api
else:
    governance_api = None

VERSION = "4.4.4"

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

logger = logging.getLogger(__name__)
sessions = {}


def _session_timeout(scope='PORTAL'):
    """Return the configured web session timeout in seconds."""
    try:
        from lib import admin_management
        return int(admin_management.session_policy(str(scope or 'PORTAL').upper())['idle_timeout_seconds'])
    except Exception:
        return max(1, int(getattr(_load_server_config(), 'session_timeout', 300)))


def _session_absolute_timeout(scope='PORTAL'):
    try:
        from lib import admin_management
        return int(admin_management.session_policy(str(scope or 'PORTAL').upper())['absolute_timeout_seconds'])
    except Exception:
        return 28800


def _portal_absolute_session_timeout():
    return _session_absolute_timeout('PORTAL')


def _session_cookie(session_id, scope='PORTAL'):
    secure = '; Secure' if os.environ.get('CX_WEB_SECURE_COOKIE', '').lower() in {'1', 'true', 'yes'} else ''
    return '{}={}; Path=/; HttpOnly; Max-Age={}; SameSite=Lax{}'.format(
        _get_cookie_name(scope), session_id, _session_absolute_timeout(scope), secure
    )

PAGE_ROUTES = {
    '/knowledge': 'knowledge.html',
    '/memory': 'memory.html',
    '/agents': 'agents.html',
    '/tasks': 'tasks.html',
    '/workspaces': 'workspaces.html',
    '/graph': 'graph.html',
    '/specs': 'specs.html',
    '/collab': 'collab.html',
    '/skills': 'skills.html',
    '/branches': 'branches.html',
    '/loops': 'loops.html',
    '/monitor': 'monitor.html',
}

if edition_features.has_feature('audit'):
    PAGE_ROUTES['/audit'] = 'audit.html'
if edition_features.has_feature('approvals'):
    PAGE_ROUTES['/approvals'] = 'approvals.html'

PUBLIC_API = {
    '/api/health',
    '/api/login',
    '/portal/api/register',
    '/portal/api/login',
}

# These routes authenticate with an Admin Token inside their handlers so the
# bootstrap CLI can operate before it has a browser session.
TOKEN_AUTH_API = {
    '/api/admin/agent/register',
    '/api/admin/agent/recover',
    '/api/agents/register',
    '/api/agents/heartbeat',
}

ADMIN_SESSION_API_PREFIXES = (
    '/api/admin/token/',
    '/api/admin/crypto/',
    '/api/admin/skill/',
    '/api/graph-executors',
)

FEATURE_ROUTE_PREFIXES = {
    'approvals': ('/api/approvals', '/approvals'),
    'audit': ('/api/audit', '/audit'),
    'ldap': ('/api/ldap',),
    'skill_token': ('/api/skill/token',),
    'orchestrator': ('/api/orchestrator',),
    'governance': ('/api/governance', '/api/agents/registry'),
    'graph_engineering': (
        '/api/graphs', '/api/graph-types', '/api/graph-versions', '/api/graph-runs',
        '/api/graph-triggers',
        '/api/graph-worker', '/api/graph/workers', '/api/graph/events',
        '/api/graph/capabilities', '/api/graph-artifacts',
        '/api/graph-executors',
        '/api/graph-dynamic', '/api/graph-assurance', '/api/a2a', '/api/telemetry',
    ),
}


def _route_feature_available(path):
    for feature, prefixes in FEATURE_ROUTE_PREFIXES.items():
        if any(path == prefix or path.startswith(prefix + '/') for prefix in prefixes):
            return edition_features.has_feature(feature)
    return True


def _graph_operation_capability(path):
    """Apply the database-authoritative Graph profile to legacy HTTP routes."""
    normalized = '/' + str(path or '').lstrip('/')
    if normalized.startswith('/api/a2a'):
        return 'a2a_gateway'
    if normalized.startswith('/api/telemetry'):
        return 'otel_export'
    if normalized.startswith('/api/graph-dynamic') or normalized.endswith('/migrate'):
        return 'graph_dynamic_migration'
    if normalized.endswith('/replay') or (normalized.startswith('/api/graph/events/inbox/') and normalized.endswith('/replay')):
        return 'graph_replay'
    if normalized.endswith('/fork'):
        return 'graph_checkpoint_fork'
    if normalized.startswith('/api/graph-assurance'):
        return 'graph_slo_readonly'
    if normalized.startswith('/api/graph-manifest') or normalized.startswith('/api/graph-compat'):
        return 'graph_manifest_draft_import'
    if normalized.startswith(('/api/graphs', '/api/graph-', '/api/graph/')):
        return 'graph_runtime_core'
    return None


def _enforce_graph_profile(path, handler=None):
    capability = _graph_operation_capability(path)
    if not capability:
        return True
    try:
        current = graph_production_profile.state(capability)
        if current == 'CONTROLLED':
            if handler is None or handler._require_admin() is None:
                return False
            graph_production_profile.require(capability, controlled=True)
        else:
            graph_production_profile.require(capability)
        return True
    except graph_production_profile.ProfileConflict as exc:
        # This helper is called from the request handler, which owns the
        # response writer; callers translate the exception into a JSON error.
        raise PermissionError('GRAPH_CAPABILITY_BLOCKED: ' + str(exc)) from exc
    except graph_production_profile.ProfileUnavailable as exc:
        raise RuntimeError('GRAPH_CAPABILITY_UNAVAILABLE: ' + str(exc)) from exc


def _is_public_api(path):
    return path in PUBLIC_API


def _uses_token_auth(path):
    return path in TOKEN_AUTH_API


def _is_admin_role(role):
    return str(role or '').strip().upper() in {'ADMIN', 'ADMINISTRATOR'}


def _get_cookie_name(scope='PORTAL'):
    """Return entry-scoped, port-specific cookie name for Web sessions."""
    # FastAPI is the network entrypoint from v4.3.0 onward.  Legacy page/API
    # handlers run in-process behind it, so they must use its runtime port
    # rather than the packaged config.json default (normally 8000).
    port = os.environ.get('MEMORY_SERVER_PORT', '').strip()
    if not port:
        port = str(_load_server_config().port)
    normalized = str(scope or '').upper()
    if normalized not in {'DASHBOARD', 'PORTAL'}:
        raise ValueError('invalid session scope')
    prefix = 'portal_session_id' if normalized == 'PORTAL' else 'dashboard_session_id'
    return f"{prefix}_{port}"

def _load_server_config():
    cfg = config.get_config()
    return cfg.server


def _product_database_display():
    dialect = str(getattr(connection, 'DATABASE_DIALECT', '') or '').lower()
    return {
        'oracle': 'Oracle',
        'postgresql': 'PostgreSQL',
        'pg': 'PostgreSQL',
        'yashandb': 'YashanDB',
    }.get(dialect, dialect or 'Database')


def _product_tier():
    return str(getattr(edition_features, 'EDITION', 'Enterprise') or 'Enterprise')


def _parse_bounded_limit(value, *, default=500, maximum=1000):
    """Parse an export limit without allowing an unbounded snapshot query."""
    if value in (None, ''):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('limit must be an integer') from exc
    if parsed < 1 or parsed > maximum:
        raise ValueError(f'limit must be between 1 and {maximum}')
    return parsed


def _portal_node_id():
    """Return a stable identifier used to isolate Portal Agent ownership."""
    cfg = _load_server_config()
    configured = getattr(cfg, 'node_id', '') or os.environ.get('MEMORY_SERVER_NODE_ID', '')
    node_id = str(configured).strip() or '{}:{}'.format(socket.gethostname(), cfg.port)
    return node_id[:128]


def _create_session(username, user_id, role, mfa_level='NONE', require_identity=False, session_scope='PORTAL'):
    created_session = None
    try:
        principal = identity_api._row(identity_api.connection.execute_query_one(
            "SELECT PRINCIPAL_ID FROM CX_HUMAN_IDENTITIES WHERE IDENTITY_TYPE = 'LOCAL' AND SUBJECT_KEY = :username",
            {'username': username},
        ))
        principal_id = str((principal or {}).get('principal_id') or user_id)
        created_session = identity_api.create_session(
            principal_id, str(user_id), _portal_node_id(), auth_method='LOCAL',
            mfa_level=mfa_level, ttl_seconds=_session_timeout(session_scope), session_scope=session_scope,
        )
        session_id = created_session['session_id']
    except Exception:
        if require_identity:
            raise
        raw = "{}:{}:{}:{}".format(username, user_id, role, time.time())
        session_id = hashlib.sha256(raw.encode()).hexdigest()
    sessions[session_id] = {
        'username': username,
        'user_id': str(user_id),
        'principal_id': principal_id if 'principal_id' in locals() else str(user_id),
        'role': role,
        'created_at': time.time(),
        'last_access': time.time(),
        'mfa_level': str(mfa_level or 'NONE').upper(),
        'session_digest': hashlib.sha256(session_id.encode('utf-8')).hexdigest(),
        'csrf_token': (created_session or {}).get('csrf_token', ''),
        'expires_at': (created_session or {}).get('expires_at', ''),
    }
    return session_id


def _set_portal_agent_context(sess):
    agent_id = sess.get('agent_id', '')
    if agent_id:
        connection.set_agent_context(agent_id)


def _clear_portal_agent_context():
    connection.set_agent_context(None)


def _resolve_session_as_schema_owner(raw_session_id, session_scope='PORTAL'):
    """Resolve human Web Sessions outside the Business Agent context."""
    previous_agent_id = connection.get_current_agent_id()
    if previous_agent_id:
        connection.set_agent_context(None)
    try:
        return identity_api.resolve_session(
            raw_session_id, ttl_seconds=_session_timeout(session_scope),
            absolute_ttl_seconds=_session_absolute_timeout(session_scope), expected_scope=session_scope,
        )
    finally:
        connection.set_agent_context(previous_agent_id)


def _resolve_session_role_as_schema_owner(principal_id):
    previous_agent_id = connection.get_current_agent_id()
    if previous_agent_id:
        connection.set_agent_context(None)
    try:
        role_row = identity_api.connection.execute_query_one(
            "SELECT ROLE_CODE FROM CX_USER_ROLES WHERE PRINCIPAL_ID = :principal_id "
            "AND STATUS = 'ACTIVE' ORDER BY VALID_FROM DESC FETCH FIRST 1 ROWS ONLY",
            {'principal_id': principal_id},
        )
        return str((role_row or {}).get('role_code') or '').upper()
    finally:
        connection.set_agent_context(previous_agent_id)


def _get_or_assign_portal_agent(user_id):
    """Reuse or claim an Agent owned by this Portal node."""
    if not user_id:
        return None
    node_id = _portal_node_id()
    attempted = set()
    assigned = connection.execute_query_one(
        "SELECT AGENT_ID FROM AGENT_REGISTRY "
        "WHERE STATUS = 'ACTIVE' AND CURRENT_USER_ID = :v_uid "
        "AND PORTAL_NODE_ID = :v_node_id "
        "ORDER BY UPDATED_AT DESC",
        {"v_uid": str(user_id), "v_node_id": node_id},
    )
    if assigned:
        candidate = agent_api.get_agent(assigned['agent_id']) or assigned
    else:
        candidate = None
    while True:
        if not candidate:
            candidate = agent_api.assign_random_pool_agent(str(user_id), node_id, attempted)
        if not candidate:
            return None
        agent_id = str(candidate.get('agent_id') or '')
        if not agent_id or agent_id in attempted:
            candidate = None
            continue
        attempted.add(agent_id)
        # Existing pool records are bound only when they are actually selected
        # by the local Portal node; this avoids silently claiming stale agents.
        try:
            registration = agent_registration.get_registration(agent_id)
            if registration and str(registration.get('status') or '').upper() != 'ACTIVE':
                agent_api.hibernate_agent(agent_id, node_id)
                candidate = None
                continue
            # This is idempotent for an already registered Agent and also
            # repairs legacy pool records missing adapter-specific credentials.
            agent_api.register_agent(
                agent_id,
                candidate.get('agent_name') or agent_id,
                agent_type=candidate.get('agent_type'),
                description=candidate.get('description'),
                capabilities=candidate.get('capabilities'),
                config=candidate.get('config'),
            )
            registration = agent_registration.get_registration(agent_id)
            if not registration:
                # Legacy records remain explicitly adopted only after the
                # adapter has had a chance to provision its runtime identity.
                registration = agent_registration.adopt_legacy_agent(
                    agent_id, created_by='portal-confirmation'
                )
            if not registration or str(registration.get('status') or '').upper() != 'ACTIVE':
                agent_api.hibernate_agent(agent_id, node_id)
                candidate = None
                continue
            # Never report an Agent as available when the database-specific
            # End User connection cannot actually be opened.
            with connection.get_connection_for_agent(agent_id):
                pass
            return candidate
        except Exception:
            logger.warning('Unable to bind Portal Agent %s to registration inventory', agent_id)
            try:
                agent_api.hibernate_agent(agent_id, node_id)
            except Exception:
                pass
        candidate = agent_api.assign_random_pool_agent(str(user_id), node_id, attempted)
    return None


def _get_session(request_handler):
    cached = getattr(request_handler, '_cx_session_cache', None)
    if cached is not None:
        return cached
    cookie = SimpleCookie(request_handler.headers.get('Cookie', ''))
    session_id = None
    session_scope = 'PORTAL' if request_handler.path.startswith('/portal') or request_handler.path == '/logout' else 'DASHBOARD'
    _cookie_name = _get_cookie_name(session_scope)
    if _cookie_name in cookie:
        session_id = cookie[_cookie_name].value
    if not session_id:
        request_handler._cx_session_cache = None
        return None
    sess = sessions.get(session_id)
    if sess:
        try:
            persisted = _resolve_session_as_schema_owner(session_id, session_scope)
            if persisted is None:
                sessions.pop(session_id, None)
                request_handler._cx_session_cache = None
                return None
            sess['principal_id'] = persisted.get('principal_id') or sess.get('principal_id')
            sess['mfa_level'] = persisted.get('mfa_level') or 'NONE'
        except Exception:
            pass
        # The cached session may predate a server restart or an earlier
        # workspace recovery fix. Restore its conversation lazily as well so
        # a valid Portal user never receives an empty history by accident.
        if session_scope == 'PORTAL' and sess.get('user_id') and not sess.get('workspace_id'):
            previous_agent_id = connection.get_current_agent_id()
            try:
                connection.set_agent_context(None)
                recent_workspace = connection.execute_query_one(
                    "SELECT WORKSPACE_ID FROM WORKSPACES "
                    "WHERE OWNER_USER_ID = :v_uid AND WORKSPACE_TYPE = 'CONVERSATION' "
                    "AND STATUS = 'ACTIVE' ORDER BY UPDATED_AT DESC",
                    {'v_uid': sess['user_id']},
                )
                if recent_workspace:
                    sess['workspace_id'] = str(recent_workspace.get('workspace_id') or recent_workspace.get('WORKSPACE_ID') or '')
            except Exception:
                logger.warning('Unable to restore cached Portal conversation workspace', exc_info=True)
            finally:
                connection.set_agent_context(previous_agent_id)
    else:
        try:
            persisted = _resolve_session_as_schema_owner(session_id, session_scope)
        except Exception:
            persisted = None
        if not persisted:
            request_handler._cx_session_cache = None
            return None
        sess = {
            'username': persisted.get('user_id') or persisted.get('principal_id'),
            'user_id': str(persisted.get('user_id') or ''),
            'principal_id': persisted.get('principal_id'),
            'role': 'USER',
            'created_at': time.time(),
            'last_access': time.time(),
        }
        try:
            role_code = _resolve_session_role_as_schema_owner(persisted.get('principal_id'))
            if role_code in {'SYSTEM_ADMIN', 'SECURITY_ADMIN'}:
                sess['role'] = 'ADMIN'
            elif role_code:
                sess['role'] = role_code
        except Exception:
            pass
        # A persisted Portal session survives a web-service restart, while
        # this in-memory cache does not. Restore the user's latest active
        # conversation so history remains available before any new message is
        # sent or an Agent is reassigned.
        if session_scope == 'PORTAL' and sess.get('user_id'):
            previous_agent_id = connection.get_current_agent_id()
            try:
                connection.set_agent_context(None)
                recent_workspace = connection.execute_query_one(
                    "SELECT WORKSPACE_ID FROM WORKSPACES "
                    "WHERE OWNER_USER_ID = :v_uid AND WORKSPACE_TYPE = 'CONVERSATION' "
                    "AND STATUS = 'ACTIVE' ORDER BY UPDATED_AT DESC",
                    {'v_uid': sess['user_id']},
                )
                if recent_workspace:
                    sess['workspace_id'] = str(recent_workspace.get('workspace_id') or recent_workspace.get('WORKSPACE_ID') or '')
            except Exception:
                logger.warning('Unable to restore Portal conversation workspace', exc_info=True)
            finally:
                connection.set_agent_context(previous_agent_id)
        sessions[session_id] = sess
    timeout = _session_timeout()
    if time.time() - sess.get('last_access', sess['created_at']) > timeout:
        sessions.pop(session_id, None)
        request_handler._cx_session_cache = None
        return None
    sess['last_access'] = time.time()
    request_handler._cx_session_cache = (session_id, sess)
    return request_handler._cx_session_cache


def _authenticate_local(username, password):
    try:
        modern = identity_api.authenticate_local(username, password)
        if modern:
            return modern
    except Exception:
        logger.debug('v4.3 identity login unavailable; using legacy verifier', exc_info=True)
    try:
        row = connection.execute_query_one(
            "SELECT user_id, username, password_hash, role, status, auth_source FROM system_users WHERE username = :uname",
            {"uname": username}
        )
        if row:
            try:
                salt_row = connection.execute_query_one(
                    "SELECT salt FROM system_users WHERE username = :uname",
                    {"uname": username}
                )
                if salt_row:
                    row['salt'] = salt_row.get('salt', '') or ''
            except Exception:
                row['salt'] = ''
    except Exception:
        return None
    if not row or row.get('status') != 'ACTIVE':
        return None
    if row.get('auth_source', 'LOCAL') != 'LOCAL':
        return None
    stored_hash = row.get('password_hash', '')
    if stored_hash and stored_hash.startswith('SHA256:'):
        expected = stored_hash[7:]
        salt = row.get('salt', '') or ''
        if salt:
            actual = hashlib.sha256((password + salt).encode()).hexdigest()
        else:
            actual = hashlib.sha256(password.encode()).hexdigest()
        if actual.upper() == expected.upper():
            return row
    return None


def _serialize_datetime(val):
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def _clean_value(value):
    if isinstance(value, dict):
        return {key: _clean_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value]
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, bytes):
        try:
            return value.decode('utf-8')
        except Exception:
            return value.hex()
    return value


def _clean_row(row):
    return _clean_value(row)


def _graph_all():
    all_edges = connection.execute_query(
        "SELECT SOURCE_ID, TARGET_ID, EDGE_TYPE, STRENGTH FROM ENTITY_EDGES "
        "ORDER BY STRENGTH DESC FETCH FIRST 300 ROWS ONLY"
    )
    endpoint_ids = []
    for edge in all_edges:
        for key in ('source_id', 'target_id'):
            value = edge.get(key)
            if value is not None and value not in endpoint_ids:
                endpoint_ids.append(value)

    all_items = []
    if endpoint_ids:
        is_pg = str(getattr(connection, 'DATABASE_DIALECT', '')).lower() in ('pg', 'postgresql')
        params = {
            'node_%d' % index: str(value) if is_pg else value
            for index, value in enumerate(endpoint_ids)
        }
        placeholders = ','.join(':%s' % key for key in params)
        entity_id_expression = 'CAST(ENTITY_ID AS TEXT)' if is_pg else 'ENTITY_ID'
        all_items.extend(connection.execute_query(
            "SELECT ENTITY_ID, TITLE, ENTITY_TYPE, CATEGORY, IMPORTANCE, STATUS "
            "FROM ENTITIES WHERE %s IN (%s)" % (entity_id_expression, placeholders),
            params,
        ))

    # Include representative nodes for every persisted type, even when that
    # type has no edge among the strongest relationships returned above.
    entity_types = connection.execute_query(
        "SELECT DISTINCT ENTITY_TYPE FROM ENTITIES ORDER BY ENTITY_TYPE"
    )
    for type_row in entity_types:
        entity_type = type_row.get('entity_type')
        if not entity_type:
            continue
        all_items.extend(connection.execute_query(
            "SELECT ENTITY_ID, TITLE, ENTITY_TYPE, CATEGORY, IMPORTANCE, STATUS "
            "FROM ENTITIES WHERE ENTITY_TYPE = :entity_type "
            "ORDER BY IMPORTANCE DESC FETCH FIRST 12 ROWS ONLY",
            {'entity_type': entity_type},
        ))
    type_colors = {
            'KNOWLEDGE': '#4a90d9', 'MEMORY': '#4fc3f7', 'TASK_OUTPUT': '#ffb74d',
            'EXPERIENCE': '#e57373', 'HARNESS_TEMPLATE': '#ba68c8', 'SPEC': '#66bb6a',
        }
    nodes = []
    known_nodes = set()
    for item in all_items:
        node_id = str(item['entity_id'])
        if node_id in known_nodes:
            continue
        known_nodes.add(node_id)
        tc = type_colors.get(item.get('entity_type', ''), '#666')
        imp = item.get('importance', 5) or 5
        try:
            imp = float(imp)
        except (TypeError, ValueError):
            imp = 5
        nodes.append({
            'id': node_id,
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
        src = e.get('source_id')
        tgt = e.get('target_id')
        if not src or not tgt or str(src) not in known_nodes or str(tgt) not in known_nodes:
            continue
        edges.append({
            'from': str(src),
            'to': str(tgt),
            'label': e.get('edge_type', ''),
            'edge_type': e.get('edge_type', ''),
            'strength': e.get('strength'),
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


def _knowledge_to_vis(principal_id=None):
    items = knowledge_api.search_knowledge(limit=500, principal_id=principal_id)
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
    version_ids = [str(i.get('version_id')) for i in items if i.get('version_id')]
    eids = [i['entity_id'] for i in items if i.get('entity_id')]
    tags_map = _get_tags_for_entities(eids)
    try:
        # Do not let the library's newest-500 window hide valid relationships
        # whose current endpoint falls just outside that display window.
        mem_edges = connection.execute_query(
            "SELECT r.SOURCE_VERSION_ID AS source_id, r.TARGET_VERSION_ID AS target_id, r.RELATION_TYPE AS edge_type, "
            "COALESCE(r.CONFIDENCE, 1) AS strength FROM CX_MEMORY_RELATIONS r "
            "WHERE r.RELATION_STATE = 'ACTIVE' AND ("
            "r.SOURCE_VERSION_ID IN (SELECT CURRENT_VERSION_ID FROM CX_MEMORY_FAMILIES WHERE CURRENT_VERSION_ID IS NOT NULL) "
            "OR r.TARGET_VERSION_ID IN (SELECT CURRENT_VERSION_ID FROM CX_MEMORY_FAMILIES WHERE CURRENT_VERSION_ID IS NOT NULL)) "
            "FETCH FIRST 1000 ROWS ONLY",
            {},
        )
    except Exception:
        mem_edges = connection.execute_query(
            "SELECT source_id, target_id, edge_type, strength FROM entity_edges "
            "WHERE source_type = 'MEMORY' OR target_id IN (%s)" % ','.join(["'%s'" % eid for eid in eids]) if eids else "FALSE",
        ) if eids else []
    endpoint_ids = {
        str(value)
        for edge in mem_edges
        for value in (edge.get('source_id'), edge.get('target_id'))
        if value and str(value) not in set(version_ids)
    }
    related_versions = []
    if endpoint_ids:
        params = {f"v{i}": value for i, value in enumerate(sorted(endpoint_ids)[:250])}
        related_versions = connection.execute_query(
            "SELECT v.VERSION_ID,v.TITLE,v.VERSION_NUMBER,v.MEMORY_TYPE,v.MEMORY_SCOPE,v.LIFECYCLE_STATE,v.CLASSIFICATION,"
            "f.FAMILY_ID,CASE WHEN f.CURRENT_VERSION_ID=v.VERSION_ID THEN 1 ELSE 0 END AS IS_CURRENT "
            "FROM CX_MEMORY_VERSIONS v LEFT JOIN CX_MEMORY_FAMILIES f ON f.FAMILY_ID=v.FAMILY_ID WHERE v.VERSION_ID IN ({})".format(
                ','.join(f":v{i}" for i in range(len(params)))
            ),
            params,
        )
    nodes = []
    for item in items:
        nodes.append({
            'id': item.get('version_id') or item['entity_id'],
            'family_id': item.get('family_id'),
            'version_id': item.get('version_id'),
            'version_number': item.get('version_number'),
            'label': (item.get('title') or '')[:60],
            'group': item.get('category') or 'general',
            'title': item.get('summary') or item.get('title') or '',
            'entity_type': 'MEMORY',
            'importance': item.get('importance', 5),
            'content': item.get('content') or '',
            'summary': item.get('summary') or '',
            'category': item.get('memory_type') or item.get('category') or '',
            'memory_scope': item.get('memory_scope') or '',
            'lifecycle_state': item.get('lifecycle_state') or item.get('status') or '',
            'visibility': item.get('visibility') or '',
            'owned_by_agent': item.get('owned_by_agent') or '',
            'tags': tags_map.get(item['entity_id'], []),
        })
    # A current-memory view needs the linked historical endpoints; otherwise
    # valid lineage edges are silently dropped by the client graph renderer.
    for item in related_versions:
        is_current = str(item.get('is_current') or '0').upper() in {'1', 'Y', 'TRUE'}
        nodes.append({
            'id': item['version_id'],
            'family_id': item.get('family_id'),
            'version_id': item['version_id'],
            'version_number': item.get('version_number'),
            'label': '{} · V{}'.format(item.get('title') or item['version_id'], item.get('version_number') or '?')[:80],
            'group': 'MEMORY' if is_current else 'MEMORY_LINEAGE',
            'entity_type': 'MEMORY' if is_current else 'MEMORY_LINEAGE',
            'title': 'Current Memory metadata.' if is_current else 'Historical lineage metadata only; this version is not returned to runtime context.',
            'category': item.get('memory_type') or '',
            'memory_scope': item.get('memory_scope') or '',
            'lifecycle_state': item.get('lifecycle_state') or '',
            'classification': item.get('classification') or '',
            'history_node': not is_current,
            'color': None if is_current else {'background': '#80909a', 'border': '#52636d'},
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
    protocol_version = "HTTP/1.1"
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
        self.send_header('Cache-Control', 'no-store, max-age=0')
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
        entry = 'PORTAL' if self.path.startswith('/portal') else 'APP'
        previous_agent_id = connection.get_current_agent_id()
        connection.set_agent_context(None)
        try:
            if not identity_api.entry_allowed(str(result[1].get('principal_id') or ''), entry):
                self._send_error(403, '{} access is disabled'.format(entry.title()))
                return None
        except Exception:
            self._send_error(503, 'Entry-access policy is unavailable')
            return None
        finally:
            connection.set_agent_context(previous_agent_id)
        return result

    def _require_admin(self):
        result = self._require_auth()
        if result is None:
            return None
        if not _is_admin_role(result[1].get('role')):
            self._send_error(403, 'Administrator role required')
            return None
        return result

    def _is_admin_session(self):
        result = _get_session(self)
        return bool(result and _is_admin_role(result[1].get('role')))

    def _authenticated_actor(self):
        """Derive an actor from the authenticated session or Agent headers."""
        agent_id = self.headers.get('X-Agent-Id', '').strip()
        if agent_id and agent_registration.authenticate_agent(
                agent_id, self.headers.get('X-Agent-Token', '').strip()):
            return agent_id
        result = _get_session(self)
        if not result:
            raise PermissionError('authenticated actor required')
        sess = result[1]
        return str(sess.get('username') or sess.get('user_id') or '')

    def _authenticated_principal(self):
        """Return server-derived actor, role, and approval groups.

        Request bodies may describe an operation, but they never define who
        performed it.  The current schema stores a single system-user role, so
        group claims are derived conservatively from that role until a separate
        directory/group provider is configured.
        """
        agent_id = self.headers.get('X-Agent-Id', '').strip()
        agent_token = self.headers.get('X-Agent-Token', '').strip()
        if agent_id and agent_registration.authenticate_agent(agent_id, agent_token):
            registration = agent_registration.get_registration(agent_id) or {}
            return {
                'actor_id': agent_id,
                'actor_type': 'AGENT',
                'role': 'AGENT',
                'groups': [],
                'registration': registration,
            }
        result = _get_session(self)
        if not result:
            raise PermissionError('authenticated actor required')
        sess = result[1]
        role = str(sess.get('role') or 'USER').upper()
        groups = {'ADMIN', 'SECURITY', 'AUDIT', 'APPROVAL'} if _is_admin_role(role) else set()
        return {
            'actor_id': str(sess.get('principal_id') or sess.get('user_id') or sess.get('username') or ''),
            'actor_type': 'HUMAN',
            'role': role,
            'groups': sorted(groups),
            'user_id': str(sess.get('user_id') or ''),
        }

    def _require_governance_admin(self):
        try:
            principal = self._authenticated_principal()
        except PermissionError as exc:
            self._send_error(401, str(exc))
            return None
        if principal.get('actor_type') != 'HUMAN' or not _is_admin_role(principal.get('role')):
            self._send_error(403, 'Administrator role required')
            return None
        return principal

    def _require_registered_session_agent(self):
        """Require a Portal session's assigned Agent to have active admission."""
        session_data = _get_session(self)
        if not session_data:
            self._send_error(401, 'Authentication required')
            return None
        sess = session_data[1]
        agent_id = str(sess.get('agent_id') or '').strip()
        if not agent_id:
            self._send_error(403, 'Registered Agent is required')
            return None
        # Admission metadata belongs to the Schema Owner.  Portal requests
        # enter the Business Agent context before authorization, and Oracle's
        # row security correctly hides AGENT_REGISTRATIONS from that identity.
        previous_agent_id = connection.get_current_agent_id()
        connection.set_agent_context(None)
        try:
            registration = agent_registration.get_registration(agent_id)
        finally:
            connection.set_agent_context(previous_agent_id)
        if not registration or str(registration.get('status') or '').upper() != 'ACTIVE':
            self._send_error(403, 'Agent registration is unavailable')
            return None
        return session_data

    def _authorize_request(self, path):
        if not _route_feature_available(path):
            self._send_error(404, 'Not found')
            return False
        try:
            if not _enforce_graph_profile(path, self):
                return False
        except PermissionError as exc:
            self._send_error(409, str(exc))
            return False
        except RuntimeError as exc:
            self._send_error(503, str(exc))
            return False
        is_api = path.startswith('/api/') or path.startswith('/portal/api/') or path.startswith('/ap/')
        if not is_api or _is_public_api(path) or _uses_token_auth(path):
            return True
        agent_id = self.headers.get('X-Agent-Id', '').strip()
        agent_token = self.headers.get('X-Agent-Token', '').strip()
        if agent_id or agent_token:
            if not agent_id or not agent_token or not agent_registration.authenticate_agent(agent_id, agent_token):
                self._send_error(401, 'Registered Agent authentication required')
                return False
            connection.set_agent_context(agent_id)
            return True
        if path.startswith(ADMIN_SESSION_API_PREFIXES):
            return self._require_admin() is not None
        if path.startswith('/api/execution/jobs/') and path.rsplit('/', 1)[-1] in {
            'approve', 'reject', 'cancel'
        }:
            return self._require_admin() is not None
        return self._require_auth() is not None

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length:
            return self.rfile.read(length)
        return b''

    def _set_context_from_session(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        agent_id = self.headers.get('X-Agent-Id', '').strip()
        agent_token = self.headers.get('X-Agent-Token', '').strip()
        if agent_id and agent_token and agent_registration.authenticate_agent(agent_id, agent_token):
            connection.set_agent_context(agent_id)
            return
        if path in ('/portal/api/register', '/portal/api/login', '/api/login', '/api/health', '/api/agents/register'):
            connection.set_agent_context(None)
            return
        result = _get_session(self)
        if result and isinstance(result, tuple) and len(result) == 2:
            sess = result[1]
            if sess and sess.get('agent_id'):
                connection.set_agent_context(sess['agent_id'])
                return
        connection.set_agent_context(None)

    def do_GET(self):
        try:
            self._set_context_from_session()
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

        if not self._authorize_request(path):
            return

        if path == '/' :
            self._send_redirect('/portal/login')
            return

        if path == '/login':
            self._serve_template('login.html')
            return

        if path == '/portal/login' or path == '/portal':
            self._serve_template('portal_login.html')
            return

        if path == '/portal/chat':
            session_data = _get_session(self)
            previous_agent_id = connection.get_current_agent_id()
            connection.set_agent_context(None)
            try:
                portal_allowed = bool(
                    session_data and identity_api.entry_allowed(
                        str(session_data[1].get('principal_id') or ''), 'PORTAL'
                    )
                )
            except Exception:
                portal_allowed = False
            finally:
                connection.set_agent_context(previous_agent_id)
            if not portal_allowed or str(session_data[1].get('mfa_level') or 'NONE').upper() == 'SETUP':
                self._send_redirect('/portal/login')
                return
            self._serve_template('portal_chat.html')
            return

        if path == '/logout':
            session_data = _get_session(self)
            if session_data and session_data[1].get('agent_id'):
                # A Portal exit/logout may only release an Agent claimed by
                # this node.  The node binding prevents cross-node recycling.
                try:
                    agent_api.hibernate_agent(session_data[1]['agent_id'], _portal_node_id())
                except Exception:
                    logger.warning('Unable to release Portal Agent during logout', exc_info=True)
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            session_ids = []
            for scope in ('PORTAL', 'DASHBOARD'):
                name = _get_cookie_name(scope)
                if name in cookies:
                    session_ids.append(cookies[name].value)
            for raw_session_id in session_ids:
                sessions.pop(raw_session_id, None)
                try:
                    identity_api.revoke_session(raw_session_id, 'logout')
                except Exception:
                    logger.warning('Unable to revoke browser session during logout', exc_info=True)
            self.send_response(302)
            self.send_header('Location', '/login')
            for scope in ('PORTAL', 'DASHBOARD'):
                self.send_header('Set-Cookie', '{}=; Path=/; Max-Age=0; SameSite=Lax'.format(_get_cookie_name(scope)))
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

        if path.startswith('/portal/api/'):
            self._handle_portal_api_get(path, qs)
            return

        if path.startswith('/static/'):
            self._serve_static(path[8:])
            return

        self._send_error(404, 'Not found')

    def do_POST(self):
        try:
            self._set_context_from_session()
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

        if not self._authorize_request(path):
            return

        if path == '/api/login':
            self._handle_login()
            return

        if path == '/api/agents/register':
            self._handle_registered_agent_register()
            return
        if path == '/api/agents/heartbeat':
            self._handle_registered_agent_heartbeat()
            return

        if path.startswith('/api/graphs') or path.startswith('/api/graph-versions/'):
            self._handle_graph_post(path)
            return
        if path.startswith('/api/graph-dynamic/'):
            self._handle_graph_dynamic_post(path)
            return
        if path.startswith('/api/a2a/'):
            self._handle_a2a_post(path)
            return
        if path == '/api/graph-executors' or path.startswith('/api/graph-executors/'):
            self._handle_graph_executor_post(path)
            return
        if path.startswith('/api/graph-triggers/'):
            self._handle_graph_trigger_post(path)
            return
        if path.startswith('/api/graph-runs/') or path == '/api/graph-runs':
            self._handle_graph_run_post(path)
            return
        if path == '/api/graph-artifacts' or path.startswith('/api/graph-artifacts/'):
            self._handle_graph_artifact_post(path)
            return
        if path.startswith('/api/graph-worker/'):
            self._handle_graph_worker_post(path)
            return
        if path == '/api/graph/events':
            self._handle_graph_event_post()
            return
        if path.startswith('/api/graph/events/inbox/') and path.endswith('/replay'):
            self._handle_graph_event_replay(path)
            return

        if path.startswith('/api/sdd/'):
            self._handle_sdd_post(path)
            return

        if path.startswith('/api/governance/'):
            self._handle_governance_post(path)
            return

        if path == '/api/memory' or path.startswith('/api/memory/'):
            self._handle_memory_lifecycle_post(path)
            return

        if path == '/api/skill/create':
            self._handle_skill_create_route()
            return

        if path.startswith('/api/skill/'):
            self._handle_skill_post(path)
            return

        if path.startswith('/api/execution/jobs/'):
            self._handle_execution_job_action(path)
            return

        # v3.9.0: Approval routes
        if path.startswith('/api/approvals/') and path.endswith('/approve'):
            self._api_approval_approve(path)
            return
        if path.startswith('/api/approvals/') and path.endswith('/reject'):
            self._api_approval_reject(path)
            return

        # v3.9.0: Agent Protocol routes
        if path == '/ap/v1/agent/tasks':
            self._api_ap_create_task()
            return
        if path.startswith('/ap/v1/agent/tasks/') and path.endswith('/steps') and self.command == 'POST':
            self._api_ap_execute_step(path)
            return

        if path == '/api/branch/fork':
            self._api_branch_fork()
            return

        if path == '/api/branch/merge':
            self._api_branch_merge()
            return

        if path == '/api/branch/fork-for-spec':
            self._api_branch_fork_for_spec()
            return

        if path == '/api/branch/merge-with-validation':
            self._api_branch_merge_with_validation()
            return

        if path == '/api/branch/fork-parallel':
            self._api_branch_fork_parallel()
            return

        if path == '/api/branch/merge-parallel':
            self._api_branch_merge_parallel()
            return

        if path == '/api/collab/distribute-plan':
            self._api_collab_distribute_plan()
            return

        if path == '/api/collab/sync-context':
            self._api_collab_sync_context()
            return

        if path.startswith('/api/branch/') and path.endswith('/abandon'):
            self._api_branch_abandon(path)
            return

        if path.startswith('/api/branch/') and path.endswith('/pause'):
            self._api_branch_pause(path)
            return

        if path.startswith('/api/branch/') and path.endswith('/resume'):
            self._api_branch_resume(path)
            return

        if path.startswith('/api/branch/') and path.endswith('/lesson'):
            self._api_branch_lesson(path)
            return

        if path.startswith('/api/branch/') and path.endswith('/extract-lessons'):
            self._api_branch_extract_lessons(path)
            return

        if path == '/portal/api/register':
            self._handle_portal_register()
            return

        if path == '/portal/api/login':
            self._handle_portal_login()
            return

        if path == '/portal/api/chat/send':
            self._handle_portal_chat_send()
            return

        if path == '/portal/api/llm-profile/select':
            self._handle_portal_llm_select()
            return

        if path == '/portal/api/chat/new':
            self._handle_portal_chat_new()
            return

        if path == '/portal/api/chat/rename':
            self._handle_portal_chat_rename()
            return

        if path == '/portal/api/chat/delete':
            self._handle_portal_chat_delete()
            return

        if path == '/portal/api/chat/switch':
            self._handle_portal_chat_switch()
            return

        if path == '/portal/api/agent/release':
            self._handle_portal_agent_release()
            return

        if path == '/api/admin/agent/register':
            self._handle_admin_agent_register()
            return

        if path == '/api/admin/agent/recover':
            self._handle_admin_agent_recover()
            return

        if path == '/api/admin/token/generate':
            self._handle_admin_token_generate()
            return

        if path == '/api/admin/token/rotate':
            self._handle_admin_token_rotate()
            return

        if path == '/api/admin/crypto/rotate':
            self._handle_admin_crypto_rotate_all()
            return

        if path.startswith('/api/admin/crypto/rotate/'):
            agent_id = path.split('/')[-1]
            self._handle_admin_crypto_rotate_agent(agent_id)
            return

        if path == '/api/admin/skill/create':
            self._handle_admin_skill_create()
            return

        if path == '/api/admin/skill/update':
            self._handle_admin_skill_update()
            return

        if path == '/api/admin/skill/delete':
            self._handle_admin_skill_delete()
            return

        if path == '/api/admin/skill/upload':
            self._handle_admin_skill_upload()
            return

        if path == '/api/loops/create':
            self._handle_loop_create()
            return
        if path == '/api/loops/delete':
            self._handle_loop_delete()
            return
        if path == '/api/loops/runs/start':
            self._handle_loop_run_start()
            return
        if path == '/api/loops/runs/pause':
            self._handle_loop_run_control('pause')
            return
        if path == '/api/loops/runs/resume':
            self._handle_loop_run_control('resume')
            return
        if path == '/api/loops/runs/stop':
            self._handle_loop_run_control('stop')
            return
        if path == '/api/loops/iterate':
            self._handle_loop_iterate()
            return
        if path == '/api/loops/hooks/add':
            self._handle_loop_hook_add()
            return
        elif path == '/api/loops/from-spec':
            self._api_loops_from_spec()
            return
        elif path == '/api/loops/collab':
            self._api_loops_collab()
            return
        elif path.startswith('/api/loops/') and path.endswith('/children'):
            self._api_loops_children(path)
            return
        elif path.startswith('/api/loops/') and path.endswith('/aggregation'):
            self._api_loops_aggregation(path)
            return
        elif path.startswith('/api/tasks/steps/') and path.endswith('/bind-loop'):
            self._api_task_step_bind_loop(path)
            return
        elif path.startswith('/api/tasks/steps/') and path.endswith('/loop'):
            self._api_task_step_loop(path)
            return
        elif path.startswith('/api/collab/') and path.endswith('/loop'):
            self._api_collab_loop(path)
            return

        self._send_error(404, 'Not found')

    def _graph_actor(self) -> str:
        return self._authenticated_actor()

    def _handle_memory_lifecycle_post(self, path):
        """Versioned Memory mutations.  The session Principal is authoritative."""
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            principal = self._authenticated_principal()
            actor = str(principal.get('actor_id') or '')
            if not actor:
                raise PermissionError('authenticated principal is unavailable')
            if path.startswith('/api/memory/snapshots/') and path.endswith('/refresh'):
                snapshot_id = path.split('/')[4]
                result = memory_lifecycle.refresh_snapshot(
                    snapshot_id, actor=actor, token_budget=int(data.get('token_budget') or 2048),
                    reason=str(data.get('reason') or ''), idempotency_key=data.get('idempotency_key'),
                    expected_snapshot_version=data.get('expected_snapshot_version'),
                )
                self._send_json(result, 201)
                return
            if path.startswith('/api/memory/jobs/') and path.endswith('/cancel'):
                if self._require_admin() is None:
                    return
                self._send_json({'success': memory_lifecycle.cancel_job(
                    path.split('/')[4], actor=actor, reason=str(data.get('reason') or ''),
                )})
                return
            if path.startswith('/api/memory/jobs/') and path.endswith('/retry'):
                if self._require_admin() is None:
                    return
                self._send_json({'success': memory_lifecycle.retry_job(
                    path.split('/')[4], actor=actor, reason=str(data.get('reason') or ''),
                )})
                return
            if path == '/api/memory/projections/rebuild':
                if self._require_admin() is None:
                    return
                self._send_json(memory_lifecycle.request_projection_rebuild(
                    actor=actor, limit=int(data.get('limit') or 500), reason=str(data.get('reason') or ''),
                ), 202)
                return
            if path.startswith('/api/memory/candidates/') and path.endswith('/activate'):
                if self._require_admin() is None:
                    return
                candidate_id = path.split('/')[4]
                self._send_json(memory_lifecycle.activate_candidate(
                    candidate_id, actor=actor, reason=str(data.get('reason') or ''),
                ))
                return
            if path == '/api/memory/jobs/run-once':
                if self._require_admin() is None:
                    return
                worker_id = str(data.get('worker_id') or f"web-{_portal_node_id()}")
                self._send_json({'result': memory_lifecycle.run_job_once(
                    worker_id, lease_seconds=int(data.get('lease_seconds') or 120),
                )})
                return
            if path == '/api/memory/snapshots':
                result = memory_lifecycle.create_snapshot(
                    str(data.get('run_id') or ''), actor=actor,
                    purpose=str(data.get('purpose') or 'RUNTIME_CONTEXT'),
                    token_budget=int(data.get('token_budget') or 2048),
                    idempotency_key=data.get('idempotency_key'),
                )
                self._send_json(result, 201)
                return
            if path == '/api/memory':
                result = memory_lifecycle.create_family(data, actor=actor, idempotency_key=data.get('idempotency_key'))
                self._send_json(result, 201)
                return
            parts = [part for part in path.split('/') if part]
            family_id = parts[2] if len(parts) > 2 else ''
            action = parts[3] if len(parts) > 3 else ''
            if action == 'versions':
                result = memory_lifecycle.create_successor(
                    family_id, str(data.get('expected_version_id') or ''), data, actor=actor,
                    idempotency_key=data.get('idempotency_key'),
                )
                self._send_json(result, 201)
                return
            if action == 'unavailable':
                result = memory_lifecycle.mark_unavailable(
                    family_id, actor=actor, reason=str(data.get('reason') or ''),
                    expected_version_id=data.get('expected_version_id'),
                )
                self._send_json(result)
                return
            if action == 'quarantine':
                if self._require_admin() is None:
                    return
                result = memory_lifecycle.quarantine_family(
                    family_id, actor=actor, reason=str(data.get('reason') or ''),
                    expected_version_id=data.get('expected_version_id'),
                )
                self._send_json(result)
                return
            if action == 'organize':
                result = memory_lifecycle.organize_memory(
                    str(data.get('version_id') or ''), actor=actor, dry_run=bool(data.get('dry_run', True)),
                    token_budget=int(data.get('token_budget') or 256),
                )
                self._send_json(result, 200)
                return
            if action == 'archive':
                if self._require_admin() is None:
                    return
                self._send_json({'success': memory_lifecycle.archive_version(
                    str(data.get('version_id') or ''), actor=actor, reason=str(data.get('reason') or ''),
                    cold=bool(data.get('cold', True)),
                )})
                return
            if action == 'discover-relations':
                result = memory_lifecycle.discover_relations(
                    str(data.get('version_id') or ''), actor=actor, limit=int(data.get('limit') or 50),
                    token_budget=int(data.get('token_budget') or 8192),
                )
                self._send_json(result)
                return
            if action == 'representations':
                representation_id = memory_lifecycle.create_representation(
                    str(data.get('version_id') or ''), str(data.get('representation_type') or ''),
                    str(data.get('body') or ''), generator_version=str(data.get('generator_version') or 'deterministic-v1'),
                    source_version_ids=data.get('source_version_ids') or [],
                )
                self._send_json({'representation_id': representation_id}, 201)
                return
            if action == 'relations':
                relation_id = memory_lifecycle.create_relation(
                    str(data.get('source_version_id') or ''), str(data.get('target_version_id') or ''),
                    str(data.get('relation_type') or ''), deterministic=bool(data.get('deterministic')),
                    confidence=data.get('confidence'), method=str(data.get('method') or 'rule-v1'),
                    evidence=data.get('evidence') or {}, actor=actor,
                )
                self._send_json({'relation_id': relation_id}, 201)
                return
            if action == 'candidates':
                result = memory_lifecycle.create_candidate(
                    str(data.get('candidate_type') or ''), str(data.get('source_version_id') or ''), data.get('proposed') or {},
                    actor=actor, confidence=data.get('confidence'), reason=str(data.get('reason') or ''),
                    idempotency_key=data.get('idempotency_key'),
                )
                self._send_json(result, 201)
                return
            if action == 'jobs':
                if self._require_admin() is None:
                    return
                result = memory_lifecycle.create_job(
                    str(data.get('job_type') or 'CONSOLIDATE'), actor=actor, scope=data.get('scope') or {},
                    dry_run=bool(data.get('dry_run', True)), reason=str(data.get('reason') or ''),
                    idempotency_key=data.get('idempotency_key'),
                )
                self._send_json(result, 201)
                return
            if action == 'usage':
                event_id = memory_lifecycle.record_usage(
                    str(data.get('version_id') or ''), str(data.get('event_type') or 'RETRIEVED'),
                    principal_id=actor, agent_id=data.get('agent_id'), run_id=data.get('run_id'),
                    purpose=str(data.get('purpose') or 'RUNTIME_CONTEXT'), outcome=data.get('outcome'),
                    value=data.get('value'), idempotency_key=data.get('idempotency_key'), metadata=data.get('metadata') or {},
                )
                self._send_json({'usage_event_id': event_id}, 201)
                return
            if action == 'reviews' and len(parts) > 4:
                if self._require_admin() is None:
                    return
                ok = memory_lifecycle.review_candidate(parts[4], str(data.get('decision') or ''), reviewer=actor, reason=str(data.get('reason') or ''))
                self._send_json({'success': ok})
                return
            self._send_error(404, 'Memory lifecycle route not found')
        except PermissionError as exc:
            self._send_json({'error': str(exc)}, 403)
        except memory_lifecycle.MemoryLifecycleError as exc:
            self._send_json({'error': str(exc), 'code': exc.code}, 409 if exc.code == 'VERSION_CONFLICT' else 400)
        except Exception as exc:
            logger.exception('memory lifecycle request failed')
            self._send_json({'error': str(exc)}, 500)

    def _handle_graph_post(self, path):
        """Graph definition lifecycle endpoints share one service contract."""
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        actor = self._graph_actor()
        try:
            if path == '/api/graphs':
                graph_id = graph_definition_api.create_graph(
                    name=data.get('name', data.get('graph_name', '')),
                    description=data.get('description'), owner_ref=actor,
                    metadata=data.get('metadata'), graph_id=data.get('graph_id'),
                )
                self._send_json({'graph_id': graph_id}, 201)
                return
            if path.startswith('/api/graphs/') and path.endswith('/import'):
                graph_id = path.split('/')[3]
                document = data.get('document') if isinstance(data.get('document'), dict) else data
                result = graph_definition_api.import_version(
                    document, actor, target_graph_id=graph_id,
                    reason=data.get('reason') or 'Imported Graph Definition',
                )
                self._send_json(result, 201)
                return
            if path.startswith('/api/graphs/') and path.endswith('/aliases'):
                graph_id = path.split('/')[3]
                alias_name = data.get('alias_name') or data.get('name')
                if not alias_name or not data.get('version_id'):
                    raise ValueError('alias_name and version_id are required')
                ok = graph_definition_api.set_alias(
                    graph_id, str(alias_name), str(data['version_id']), actor,
                    data.get('reason') or 'Alias updated',
                )
                self._send_json({'success': ok, 'alias_name': alias_name}, 201)
                return
            if path.startswith('/api/graphs/') and path.endswith('/triggers'):
                graph_id = path.split('/')[3]
                trigger_id = graph_event_api.register_trigger(
                    data.get('graph_version_id', ''), data.get('kind', ''),
                    data.get('config') or {}, actor, data.get('reason', ''), graph_id,
                )
                self._send_json({'trigger_id': trigger_id, 'status': 'ACTIVE'}, 201)
                return
            if path.startswith('/api/graphs/') and path.endswith('/versions'):
                graph_id = path.split('/')[3]
                version_id = graph_definition_api.create_version(
                    graph_id, data.get('nodes') or [], data.get('edges') or [],
                    version_label=data.get('version_label'), parent_version_id=data.get('parent_version_id'),
                    actor_id=actor, reason=data.get('reason') or 'Draft created',
                    source_run_id=data.get('source_run_id'), source_checkpoint_id=data.get('source_checkpoint_id'),
                    input_schema=data.get('input_schema'), output_schema=data.get('output_schema'),
                    budget=data.get('budget'), version_id=data.get('version_id'),
                )
                self._send_json({'graph_version_id': version_id, 'status': 'DRAFT'}, 201)
                return
            if path.startswith('/api/graph-versions/'):
                parts = path.split('/')
                version_id = parts[3]
                action = parts[4] if len(parts) > 4 else ''
                if action == 'compile':
                    result = graph_compiler.compile_version(version_id, persist=True)
                    self._send_json(result, 200 if result.get('valid') else 422)
                    return
                if action == 'publish':
                    result = graph_compiler.compile_and_publish(version_id, actor, data.get('reason') or 'Published after validation')
                    self._send_json(result, 200 if result.get('published') else 422)
                    return
                if action in {'deprecate', 'archive'}:
                    status = 'DEPRECATED' if action == 'deprecate' else 'ARCHIVED'
                    ok = graph_definition_api.transition_version(version_id, status, actor, data.get('reason') or f'{action}d by actor')
                    self._send_json({'success': ok, 'status': status})
                    return
                self._send_error(404, 'Unknown Graph Version action')
                return
            self._send_error(404, 'Unknown Graph endpoint')
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('graph definition request failed')
            self._send_error(500, str(exc))

    def _handle_graph_dynamic_post(self, path):
        """Preview-only Dynamic Graph commands remain behind normal session auth."""
        try:
            data = json.loads(self._read_body() or b'{}')
            actor = self._graph_actor()
            if path == '/api/graph-dynamic/proposals':
                result = graph_dynamic.create_draft(
                    str(data.get('source_version_id') or ''), data.get('operations') or [], actor,
                    str(data.get('reason') or ''), run_id=str(data.get('run_id') or ''),
                    checkpoint_id=str(data.get('checkpoint_id') or ''), expected_version=str(data.get('expected_version') or ''),
                )
                self._send_json(result, 201)
                return
            self._send_error(404, 'Unknown Dynamic Graph endpoint')
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('dynamic Graph request failed')
            self._send_error(500, str(exc))

    def _handle_a2a_post(self, path):
        """A2A remains an authenticated preview adapter over existing Graph Runs."""
        try:
            data = json.loads(self._read_body() or b'{}')
            principal = self._authenticated_principal()
            actor = str(principal.get('actor_id') or '')
            if path == '/api/a2a/tasks':
                result = a2a_gateway.create_task(
                    str(data.get('graph_version_id') or ''), str(data.get('plan_id') or ''), actor,
                    input_state=data.get('input_state') or {}, budget=data.get('budget') or {},
                    idempotency_key=data.get('idempotency_key'),
                )
                self._send_json(result, 201)
                return
            if path.startswith('/api/a2a/tasks/') and path.endswith('/cancel'):
                task_id = path.split('/')[4]
                self._send_json({'success': a2a_gateway.cancel_task(task_id, actor, str(data.get('reason') or ''))})
                return
            self._send_error(404, 'Unknown A2A endpoint')
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('A2A request failed')
            self._send_error(500, str(exc))

    def _graph_executor_payload(self, include_inactive=False):
        builtins = []
        for manifest in graph_executor.builtin_executor_manifests():
            item = dict(manifest)
            item.update({
                'source': 'BUILTIN', 'status': 'ACTIVE', 'immutable': True,
                'executor_id': 'BUILTIN_' + str(item['name']),
            })
            builtins.append(item)
        persisted = graph_executor.list_persisted_manifests(
            connection, include_inactive=include_inactive,
        )
        for item in persisted:
            item['source'] = 'DATABASE'
            item['immutable'] = False
        return builtins + persisted

    def _handle_graph_executor_post(self, path):
        if self._require_admin() is None:
            return
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        actor = self._authenticated_actor()
        try:
            if path == '/api/graph-executors':
                manifest = data.get('manifest') if isinstance(data.get('manifest'), dict) else data
                executor_id = graph_executor.register_persisted_manifest(connection, manifest, actor)
                self._send_json({'executor_id': executor_id, 'status': 'ACTIVE'}, 201)
                return
            parts = [part for part in path.split('/') if part]
            executor_id = parts[2] if len(parts) > 2 else ''
            action = parts[3] if len(parts) > 3 else ''
            if action in {'activate', 'disable', 'deprecate'}:
                status = {
                    'activate': 'ACTIVE', 'disable': 'DISABLED', 'deprecate': 'DEPRECATED',
                }[action]
            elif action == 'status':
                status = str(data.get('status') or '').upper()
            else:
                self._send_error(404, 'Unknown Graph Executor action')
                return
            ok = graph_executor.set_persisted_status(
                connection, executor_id, status, actor, data.get('reason', ''),
            )
            if not ok:
                self._send_error(404, 'Graph Executor not found')
                return
            self._send_json({'success': True, 'executor_id': executor_id, 'status': status})
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('graph executor request failed')
            self._send_error(500, str(exc))

    def _handle_graph_trigger_post(self, path):
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        actor = self._graph_actor()
        try:
            parts = [part for part in path.split('/') if part]
            trigger_id = parts[2] if len(parts) > 2 else ''
            if len(parts) != 4 or parts[3] != 'fire':
                self._send_error(404, 'Unknown Graph Trigger action')
                return
            self._send_json(graph_event_api.fire_trigger(
                trigger_id, data.get('payload') or {}, actor,
                data.get('authentication'), data.get('idempotency_key'),
            ), 201)
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('graph trigger request failed')
            self._send_error(500, str(exc))

    def _handle_graph_run_post(self, path):
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        actor = self._graph_actor()
        try:
            if path == '/api/graph-runs':
                run_id = graph_runtime.create_run(
                    data.get('graph_version_id', ''), data.get('plan_id', ''), actor,
                    initial_state=data.get('initial_state') or {}, budget=data.get('budget') or {},
                    idempotency_key=data.get('idempotency_key'),
                )
                self._send_json({'run_id': run_id, 'status': 'RUNNING'}, 201)
                return
            parts = [part for part in path.split('/') if part]
            run_id = parts[2] if len(parts) > 2 else ''
            action = parts[3] if len(parts) > 3 else ''
            if action == 'cancel':
                ok = graph_runtime.cancel_run(run_id, actor, data.get('reason', ''))
                self._send_json({'success': ok})
                return
            if action == 'pause':
                self._send_json({'success': graph_runtime.pause_run(run_id, actor, data.get('reason', ''))})
                return
            if action == 'resume':
                self._send_json({'success': graph_runtime.resume_run(run_id, actor, data.get('reason', ''))})
                return
            if action == 'fork':
                child_id = graph_runtime.fork_run(run_id, actor, data.get('reason', ''), data.get('idempotency_key'))
                self._send_json({'success': True, 'run_id': child_id, 'parent_run_id': run_id}, 201)
                return
            if action == 'migrate':
                result = graph_runtime.migrate_run(
                    run_id, data.get('target_version_id', ''), actor, data.get('reason', ''), data.get('mapping') or {},
                )
                self._send_json(result)
                return
            if action == 'nodes' and len(parts) >= 6:
                node_run_id, node_action = parts[4], parts[5]
                if node_action == 'retry':
                    ok = graph_runtime.retry_node(
                        run_id, node_run_id, actor, data.get('reason', ''),
                        data.get('confirmation'),
                    )
                elif node_action == 'skip':
                    ok = graph_runtime.skip_node(run_id, node_run_id, actor, data.get('reason', ''), data.get('output_state') or {})
                elif node_action == 'force-route':
                    ok = graph_runtime.force_route(run_id, node_run_id, data.get('edge_id', ''), actor, data.get('reason', ''))
                elif node_action == 'compensate':
                    ok = graph_runtime.compensate(run_id, node_run_id, actor, data.get('reason', ''))
                else:
                    self._send_error(404, 'Unknown Graph Node action')
                    return
                self._send_json({'success': bool(ok), 'run_id': run_id, 'node_run_id': node_run_id})
                return
            if action == 'attempts' and len(parts) >= 6 and parts[5] == 'reassign':
                attempt_id = parts[4]
                ok = graph_runtime.reassign_attempt(
                    attempt_id, actor, data.get('reason', ''), data.get('worker_id'),
                )
                self._send_json({'success': bool(ok), 'run_id': run_id, 'attempt_id': attempt_id})
                return
            if action == 'recover':
                self._send_json({'run_id': run_id, 'state': graph_runtime.recover_state(run_id)})
                return
            if action == 'state' and len(parts) >= 5 and parts[4] == 'rotate-key':
                if self._require_admin() is None:
                    return
                result = graph_runtime.rotate_run_state_from_environment(
                    run_id, actor, data.get('reason', ''),
                )
                self._send_json(result)
                return
            self._send_error(404, 'Unknown Graph Run action')
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('graph run request failed')
            self._send_error(500, str(exc))

    def _handle_graph_artifact_post(self, path):
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        actor = self._graph_actor()
        try:
            if path == '/api/graph-artifacts':
                encoded = data.get('content_base64', '')
                if not encoded:
                    raise ValueError('content_base64 is required')
                content = base64.b64decode(encoded, validate=True)
                result = graph_runtime.put_artifact(
                    content, data.get('owner_ref') or actor, data.get('media_type', 'application/octet-stream'),
                    data.get('classification', 'INTERNAL'),
                )
                self._send_json(result, 201)
                return
            artifact_id = path.split('/')[3] if len(path.split('/')) > 3 else ''
            action = path.split('/')[4] if len(path.split('/')) > 4 else ''
            if action == 'retention':
                ok = graph_runtime.set_artifact_retention(artifact_id, data.get('retention_until'), actor, data.get('reason', ''))
            elif action == 'legal-hold':
                ok = graph_runtime.set_artifact_legal_hold(artifact_id, bool(data.get('enabled', True)), actor, data.get('reason', ''))
            elif action == 'purge':
                count = graph_runtime.purge_expired_artifacts(actor, int(data.get('limit', 100)))
                self._send_json({'success': True, 'deleted': count})
                return
            else:
                self._send_error(404, 'Unknown Artifact action')
                return
            self._send_json({'success': bool(ok), 'artifact_id': artifact_id})
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('graph artifact request failed')
            self._send_error(500, str(exc))

    def _handle_graph_worker_post(self, path):
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            if path == '/api/graph-worker/advertise':
                result = graph_worker.advertise(
                    data.get('worker_id', ''), data.get('runtime', 'generic'),
                    data.get('capabilities') or [], data.get('agent_id'), data.get('node_id'),
                )
                self._send_json(result, 200)
                return
            if path == '/api/graph-worker/claim':
                result = graph_worker.claim(
                    data.get('worker_id', ''), data.get('runtime', 'generic'),
                    data.get('capabilities') or [], int(data.get('lease_seconds', 120)),
                    data.get('agent_id'), data.get('node_id'), data.get('node_key'),
                )
                self._send_json(result or {'task': None}, 200)
                return
            if path == '/api/graph-worker/heartbeat':
                self._send_json({'success': graph_worker.heartbeat(data.get('lease_token', ''), int(data.get('lease_seconds', 120)))})
                return
            if path == '/api/graph-worker/checkpoint':
                self._send_json(graph_worker.checkpoint(data.get('lease_token', ''), data.get('delta') or {}, self._graph_actor(), data.get('reducer_evidence')))
                return
            if path == '/api/graph-worker/complete':
                self._send_json(graph_worker.complete(data.get('lease_token', ''), data.get('output_state') or {}, self._graph_actor(), data.get('evidence')))
                return
            if path == '/api/graph-worker/fail':
                self._send_json({'success': graph_worker.fail(data.get('lease_token', ''), data.get('error_code', 'WORKER_ERROR'), data.get('error_message', ''), self._graph_actor())})
                return
            self._send_error(404, 'Unknown Graph Worker operation')
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('graph worker request failed')
            self._send_error(500, str(exc))

    def _handle_graph_event_post(self):
        try:
            data = json.loads(self._read_body() or b'{}')
            trusted_subject = self._graph_actor()
            result = graph_event_api.receive(
                data.get('source_ref', ''), data.get('event_type', ''), data.get('schema_version', '1'),
                data.get('idempotency_key', ''), data.get('payload') or {}, data.get('authentication'),
                trusted_subject=trusted_subject,
            )
            self._send_json(result, 200 if result.get('duplicate') else 202)
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def _handle_graph_event_replay(self, path):
        try:
            data = json.loads(self._read_body() or b'{}')
            actor = self._graph_actor()
            inbox_id = path.split('/')[5] if len(path.split('/')) > 5 else ''
            result = graph_event_api.replay_dead_letter(inbox_id, actor, data.get('reason', ''))
            self._send_json(result, 200)
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as exc:
            logger.exception('graph event replay request failed')
            self._send_error(500, str(exc))

    def _handle_login(self):
        try:
            body = self._read_body()
            data = json.loads(body)
            username = data.get('username', '')
            password = data.get('password', '')
        except Exception:
            self._send_json({'success': False, 'error': 'Invalid request'}, 400)
            return

        user = _authenticate_local(username, password)
        if not user:
            self._send_json({'success': False, 'error': 'Invalid credentials'}, 401)
            return

        session_id = _create_session(
            user['username'], str(user['user_id']), user.get('role', 'user'), session_scope='DASHBOARD'
        )
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', _session_cookie(session_id, 'DASHBOARD'))
        body = json.dumps({'success': True, 'session_id': session_id}).encode()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_registered_agent_register(self):
        """Bootstrap registration is admin-token protected and one-time secret returning."""
        try:
            data = json.loads(self._read_body() or b'{}')
        except Exception:
            self._send_json({'error': 'Invalid request body'}, 400)
            return
        admin_token = str(data.get('admin_token') or '')
        if not admin_token or not agent_api.verify_admin_token(admin_token):
            self._send_json({'error': 'Admin token verification failed'}, 403)
            return
        try:
            result = agent_registration.register_agent(
                agent_id=data.get('agent_id', ''), owner_ref=data.get('owner_ref', 'administrator'),
                runtime=data.get('runtime', data.get('agent_type', 'generic')),
                environment=data.get('environment', 'managed'), node_id=data.get('node_id', ''),
                capabilities=data.get('capabilities') or [], credential_version=data.get('credential_version', '1'),
                expires_at=None, idempotency_key=data.get('idempotency_key'), created_by='admin-token',
            )
            if not result:
                self._send_json({'error': 'v4.1.0 governance migration is not installed'}, 503)
                return
            self._send_json({
                'agent_id': result.get('agent_id'), 'status': result.get('status'),
                'credential': result.get('credential'), 'credential_version': result.get('credential_version'),
                'idempotent': result.get('idempotent', False),
            }, 201 if not result.get('idempotent') else 200)
        except ValueError as exc:
            self._send_json({'error': str(exc)}, 409)
        except Exception as exc:
            self._send_json({'error': str(exc)}, 500)

    def _handle_registered_agent_heartbeat(self):
        agent_id = self.headers.get('X-Agent-Id', '').strip()
        credential = self.headers.get('X-Agent-Token', '').strip()
        if not agent_id or not credential or not agent_registration.heartbeat(agent_id, credential):
            self._send_json({'success': False, 'error': 'Registered Agent authentication failed'}, 401)
            return
        self._send_json({'success': True, 'agent_id': agent_id, 'last_seen': True})

    def _handle_governance_post(self, path):
        if governance_api is None:
            self._send_error(404, 'Enterprise governance is unavailable in Community Edition')
            return
        try:
            data = json.loads(self._read_body() or b'{}')
            principal = self._authenticated_principal()
            actor = principal['actor_id']
            actor_groups = principal.get('groups') or []
            actor_role = principal.get('role') or ''
            if path == '/api/governance/resources':
                if self._require_governance_admin() is None:
                    return
                result = governance_api.create_resource(
                    resource_id=data.get('resource_id', ''), resource_type=data.get('resource_type', ''),
                    owner_ref=data.get('owner_ref', actor), classification=data.get('classification', 'UNKNOWN'),
                    environment=data.get('environment', 'PRODUCTION'), metadata=data.get('metadata'), actor_id=actor,
                )
                self._send_json(result, 201)
                return
            if path == '/api/governance/policies':
                if self._require_governance_admin() is None:
                    return
                result = governance_api.create_policy(
                    policy_id=data.get('policy_id') or governance_api._id('GPOL'),
                    resource_id=data.get('resource_id', ''), actions=data.get('actions') or [],
                    subjects=data.get('subjects') or ['*'], classification=data.get('classification', 'UNKNOWN'),
                    purpose=data.get('purpose', '*'), environment=data.get('environment', '*'),
                    decision=data.get('decision', 'DENY'), requires_approval=bool(data.get('requires_approval')),
                    policy_version=data.get('policy_version', '1'),
                    expires_at=governance_api._as_datetime(data.get('expires_at')),
                    actor_id=actor,
                )
                self._send_json(result, 201)
                return
            if path == '/api/governance/decide':
                result = governance_api.evaluate_access(
                    agent_id=actor, resource_id=data.get('resource_id', ''), action=data.get('action', ''),
                    classification=data.get('classification', 'UNKNOWN'), purpose=data.get('purpose', ''),
                    environment=data.get('environment', ''), correlation_id=data.get('correlation_id'),
                )
                if result.get('decision') == 'APPROVAL_REQUIRED':
                    result['approval'] = governance_api.create_approval_request(
                        actor, data.get('resource_id', ''), data.get('action', ''), result,
                        required_approvals=int(data.get('required_approvals', 1)),
                        eligible_groups=(data.get('eligible_groups') or ['SECURITY'])
                        if principal.get('actor_type') == 'HUMAN' and _is_admin_role(actor_role)
                        else ['SECURITY'],
                        prohibited_combinations=(data.get('prohibited_combinations') or [])
                        if principal.get('actor_type') == 'HUMAN' and _is_admin_role(actor_role)
                        else [],
                        reason=data.get('reason', 'Governed high-risk operation'),
                    )
                self._send_json(result, 202 if result.get('decision') == 'APPROVAL_REQUIRED' else 200)
                return
            if path == '/api/governance/approvals':
                result = governance_api.create_approval_request(
                    actor, data.get('resource_id', ''), data.get('action', ''),
                    required_approvals=int(data.get('required_approvals', 1)),
                    eligible_groups=(data.get('eligible_groups') or ['SECURITY'])
                    if principal.get('actor_type') == 'HUMAN' and _is_admin_role(actor_role)
                    else ['SECURITY'],
                    prohibited_combinations=(data.get('prohibited_combinations') or [])
                    if principal.get('actor_type') == 'HUMAN' and _is_admin_role(actor_role)
                    else [],
                    deadline=governance_api._as_datetime(data.get('deadline')),
                    post_review_required=bool(data.get('post_review_required')),
                    reason=data.get('reason', ''), idempotency_key=data.get('idempotency_key'),
                )
                self._send_json(result, 201)
                return
            if path.startswith('/api/governance/approvals/') and path.endswith('/decision'):
                approval_id = path.split('/')[-2]
                result = governance_api.record_approval_decision(
                    approval_id, actor, data.get('decision', ''),
                    actor_groups=actor_groups, reason=data.get('reason', ''), role=actor_role,
                )
                self._send_json(result)
                return
            if path == '/api/governance/emergency':
                if self._require_governance_admin() is None:
                    return
                result = governance_api.emergency_disable_agent(
                    data.get('agent_id', ''), actor, data.get('reason', ''), data.get('idempotency_key'),
                )
                self._send_json(result, 202)
                return
            if path == '/api/governance/grants':
                if self._require_governance_admin() is None:
                    return
                result = governance_api.create_grant(
                    grant_id=data.get('grant_id') or governance_api._id('GGRANT'),
                    subject_id=data.get('subject_id', ''), resource_id=data.get('resource_id', ''),
                    actions=data.get('actions') or [], purpose=data.get('purpose', '*'),
                    environment=data.get('environment', '*'), policy_version=data.get('policy_version', '1'),
                    issued_by=actor, starts_at=data.get('starts_at'), expires_at=data.get('expires_at'),
                )
                self._send_json(result, 201)
                return
            if path.startswith('/api/governance/grants/') and path.endswith('/revoke'):
                if self._require_governance_admin() is None:
                    return
                grant_id = path.split('/')[-2]
                result = governance_api.revoke_grant(
                    grant_id, actor, data.get('reason', ''),
                )
                self._send_json({'grant_id': grant_id, 'revoked': result})
                return
            if path.startswith('/api/governance/emergency/') and path.endswith('/retry'):
                if self._require_governance_admin() is None:
                    return
                operation_id = path.split('/')[-2]
                operation = governance_api.execute_query_one(
                    'SELECT OPERATION_ID, AGENT_ID, REASON, IDEMPOTENCY_KEY FROM GOV_EMERGENCY_OPS '
                    'WHERE OPERATION_ID = :operation_id', {'operation_id': operation_id},
                )
                if not operation:
                    self._send_error(404, 'Emergency operation not found')
                    return
                result = governance_api.emergency_disable_agent(
                    operation.get('agent_id', ''), actor, operation.get('reason', ''),
                    operation.get('idempotency_key'),
                )
                self._send_json(result, 202)
                return
            if path == '/api/governance/retention':
                if self._require_governance_admin() is None:
                    return
                result = governance_api.create_retention_policy(
                    data.get('retention_id') or governance_api._id('GRET'),
                    int(data.get('hot_days', 90)), data.get('archive_target', ''),
                    int(data.get('delete_after_days', 365)), actor,
                )
                self._send_json(result, 201)
                return
            if path == '/api/governance/legal-holds':
                if self._require_governance_admin() is None:
                    return
                ok = governance_api.add_legal_hold(
                    data.get('hold_id') or governance_api._id('GHOLD'), data.get('scope', '*'), data.get('reason', ''), actor,
                )
                self._send_json({'success': ok}, 201)
                return
            self._send_error(404, 'Governance route not found')
        except PermissionError as exc:
            self._send_json({'error': str(exc)}, 403)
        except ValueError as exc:
            self._send_json({'error': str(exc)}, 400)
        except Exception as exc:
            logger.exception('governance request failed')
            self._send_json({'error': str(exc)}, 500)

    def _handle_api_get(self, path, qs):
        try:
            if path == '/api/health':
                self._send_json({'status': 'ok', 'version': VERSION})
            elif path == '/api/agents/database-endpoint':
                principal = self._authenticated_principal()
                if principal.get('actor_type') != 'AGENT':
                    self._send_error(403, 'Registered Agent identity required')
                    return
                self._send_json(platform_agent_pool.discover_agent_endpoint(str(principal.get('actor_id') or '')))
            elif path == '/api/session/heartbeat':
                sd = _get_session(self)
                if sd:
                    self._send_json({'status': 'ok', 'session': 'active'})
                else:
                    self._send_json({'status': 'expired'}, 401)
            elif path == '/api/graph-executors':
                if self._require_admin() is None:
                    return
                include_inactive = qs.get('include_inactive', ['false'])[0].lower() == 'true'
                self._send_json({'executors': self._graph_executor_payload(include_inactive)})
            elif path.startswith('/api/graph-executors/'):
                if self._require_admin() is None:
                    return
                executor_id = path.split('/')[3] if len(path.split('/')) > 3 else ''
                items = self._graph_executor_payload(include_inactive=True)
                item = next((item for item in items if str(item.get('executor_id')) == executor_id), None)
                if not item:
                    self._send_error(404, 'Graph Executor not found')
                    return
                self._send_json(item)
            elif path == '/api/knowledge':
                principal = self._authenticated_principal()
                self._send_json(_knowledge_to_vis(principal.get('actor_id') if principal else None))
            elif path == '/api/memory':
                self._send_json(_memory_to_vis())
            elif path == '/api/memory/jobs':
                self._send_json({'jobs': memory_lifecycle.list_jobs(int(qs.get('limit', ['100'])[0]))})
            elif path == '/api/memory/projections/metrics':
                self._send_json(memory_lifecycle.projection_metrics())
            elif path.startswith('/api/memory/snapshots/') and path.endswith('/diff'):
                snapshot_id = path.split('/')[4]
                self._send_json(memory_lifecycle.snapshot_diff(snapshot_id))
            elif path.startswith('/api/memory/snapshots/') and path.endswith('/resolve'):
                snapshot_id = path.split('/')[4]
                self._send_json(memory_lifecycle.resolve_snapshot(
                    snapshot_id, continuation=qs.get('continuation', ['PAUSE'])[0],
                ))
            elif path == '/api/memory/policies':
                self._send_json({'policies': connection.execute_query(
                    'SELECT POLICY_ID, POLICY_NAME, POLICY_VERSION, STATUS, POLICY_JSON, UPDATED_AT FROM CX_MEMORY_POLICIES ORDER BY UPDATED_AT DESC FETCH FIRST :lim ROWS ONLY',
                    {'lim': max(1, min(int(qs.get('limit', ['100'])[0]), 200))},
                )})
            elif path == '/api/memory/candidates':
                self._send_json({'candidates': connection.execute_query(
                    'SELECT CANDIDATE_ID, CANDIDATE_TYPE, SOURCE_VERSION_ID, TARGET_VERSION_ID, CONFIDENCE, STATUS, POLICY_RESULT, CREATED_BY, REASON, CREATED_AT, UPDATED_AT FROM CX_MEMORY_CANDIDATES ORDER BY UPDATED_AT DESC FETCH FIRST :lim ROWS ONLY',
                    {'lim': max(1, min(int(qs.get('limit', ['100'])[0]), 200))},
                )})
            elif path.startswith('/api/memory/') and path.endswith('/chain'):
                family_id = path.split('/')[3]
                detail = memory_lifecycle.get_family(family_id)
                if not detail or not detail.get('current'):
                    self._send_error(404, 'Memory family not found')
                    return
                self._send_json(memory_lifecycle.chain(
                    str(detail['current']['version_id']), hops=int(qs.get('hops', ['2'])[0]), limit=int(qs.get('limit', ['100'])[0]),
                ))
            elif path.startswith('/api/memory/'):
                family_id = path.split('/')[3]
                detail = memory_lifecycle.get_family(family_id, include_history=qs.get('history', ['false'])[0].lower() == 'true')
                if not detail:
                    self._send_error(404, 'Memory family not found')
                    return
                self._send_json(detail)
            elif path == '/api/agents':
                self._api_agents()
            elif path == '/api/graphs':
                self._send_json({'graphs': graph_definition_api.list_graphs(
                    status=qs.get('status', [None])[0], owner_ref=qs.get('owner_ref', [None])[0],
                    limit=int(qs.get('limit', ['100'])[0]),
                )})
            elif path.startswith('/api/graphs/') and path.endswith('/versions'):
                graph_id = path.split('/')[3]
                self._send_json({'versions': graph_definition_api.list_versions(
                    graph_id, status=qs.get('status', [None])[0], limit=int(qs.get('limit', ['100'])[0])
                )})
            elif path.startswith('/api/graphs/') and path.endswith('/triggers'):
                graph_id = path.split('/')[3]
                graph = graph_definition_api.get_graph(graph_id)
                if not graph:
                    self._send_error(404, 'Graph not found')
                    return
                self._send_json({'triggers': graph_event_api.list_triggers(
                    qs.get('graph_version_id', [None])[0], int(qs.get('limit', ['100'])[0])
                )})
            elif path.startswith('/api/graphs/') and path.endswith('/aliases'):
                graph_id = path.split('/')[3]
                self._send_json({'aliases': graph_definition_api.list_aliases(
                    graph_id, limit=int(qs.get('limit', ['100'])[0])
                )})
            elif path.startswith('/api/graphs/'):
                graph_id = path.split('/')[3]
                graph = graph_definition_api.get_graph(graph_id)
                if not graph:
                    self._send_error(404, 'Graph not found')
                    return
                self._send_json(graph)
            elif path.startswith('/api/graph-versions/') and path.endswith('/export'):
                version_id = path.split('/')[3]
                self._send_json(graph_definition_api.export_version(
                    version_id, include_status=qs.get('include_status', ['false'])[0].lower() == 'true'
                ))
            elif path == '/api/graph-types':
                self._send_json({'types': graph_definition_api.list_types(
                    qs.get('kind', [None])[0], int(qs.get('limit', ['200'])[0])
                )})
            elif path.startswith('/api/graph-versions/'):
                version_id = path.split('/')[3]
                version = graph_definition_api.get_version(version_id, include_topology=True)
                if not version:
                    self._send_error(404, 'Graph Version not found')
                    return
                self._send_json(version)
            elif path == '/api/graph-runs':
                self._send_json({'runs': graph_runtime.list_runs(
                    status=qs.get('status', [None])[0], actor_id=qs.get('actor_id', [None])[0],
                    limit=int(qs.get('limit', ['100'])[0]),
                )})
            elif path == '/api/graph-assurance/invariants':
                if self._require_admin() is None:
                    return
                self._send_json(graph_assurance.invariant_scan())
            elif path == '/api/graph-assurance/evidence':
                if self._require_admin() is None:
                    return
                self._send_json({'evidence': graph_assurance.list_evidence(
                    qs.get('run_id', [None])[0], int(qs.get('limit', ['100'])[0]),
                )})
            elif path == '/api/graph-dynamic/proposals':
                if self._require_admin() is None:
                    return
                self._send_json({'proposals': graph_dynamic.list_proposals(int(qs.get('limit', ['100'])[0]))})
            elif path == '/api/a2a/agent-card':
                principal = self._authenticated_principal()
                self._send_json(a2a_gateway.agent_card(
                    {'agent_name': 'Chuanxu Graph Gateway', 'skills': []}, authenticated=bool(principal),
                ))
            elif path.startswith('/api/a2a/tasks/'):
                principal = self._authenticated_principal()
                task_id = path.split('/')[4] if len(path.split('/')) > 4 else ''
                task = a2a_gateway.get_task(task_id, str(principal.get('actor_id') or ''))
                if not task:
                    self._send_error(404, 'A2A task not found')
                    return
                self._send_json(task)
            elif path == '/api/telemetry/status':
                if self._require_admin() is None:
                    return
                self._send_json({'enabled': graph_telemetry.enabled(), 'mapping_version': graph_telemetry.MAPPING_VERSION,
                                 'redaction': 'METADATA_ONLY'})
            elif path == '/api/graph-artifacts':
                self._send_json({'artifacts': graph_runtime.list_artifacts(
                    owner_ref=qs.get('owner_ref', [None])[0],
                    classification=qs.get('classification', [None])[0],
                    include_held=qs.get('include_held', ['true'])[0].lower() != 'false',
                    limit=int(qs.get('limit', ['100'])[0]),
                )})
            elif path.startswith('/api/graph-artifacts/'):
                artifact_id = path.split('/')[3]
                artifact = graph_runtime.get_artifact(
                    artifact_id, include_content=qs.get('include_content', ['false'])[0].lower() == 'true',
                )
                if not artifact:
                    self._send_error(404, 'Artifact not found')
                    return
                if isinstance(artifact.get('content'), (bytes, bytearray)):
                    artifact['content_base64'] = base64.b64encode(artifact.pop('content')).decode('ascii')
                self._send_json(artifact)
            elif path.startswith('/api/graph-runs/') and path.endswith('/state'):
                run_id = path.split('/')[3]
                self._send_json({'run_id': run_id, 'state': graph_runtime.recover_state(run_id)})
            elif path.startswith('/api/graph-runs/') and path.endswith('/evidence'):
                # Run evidence contains a broad, redacted operational snapshot.
                # Keep export behind the administrator boundary and require an
                # explicit reason so the action is attributable in governance.
                if self._require_admin() is None:
                    return
                run_id = path.split('/')[3]
                reason = str(qs.get('reason', [''])[0] or '').strip()
                if not reason:
                    self._send_error(422, 'evidence export reason is required')
                    return
                if len(reason) > 2000:
                    self._send_error(422, 'evidence export reason is too long')
                    return
                try:
                    limit = _parse_bounded_limit(qs.get('limit', [None])[0])
                    result = graph_runtime.export_run_evidence(
                        run_id, self._authenticated_actor(), reason, limit=limit,
                    )
                except ValueError as exc:
                    if 'Graph Run not found' in str(exc):
                        self._send_error(404, str(exc))
                    else:
                        self._send_error(422, str(exc))
                    return
                self._send_json(result)
            elif path.startswith('/api/graph-runs/') and path.endswith('/snapshot'):
                run_id = path.split('/')[3]
                snapshot = graph_runtime.get_run_snapshot(run_id, int(qs.get('limit', ['100'])[0]))
                if not snapshot:
                    self._send_error(404, 'Graph Run not found')
                    return
                self._send_json(snapshot)
            elif path.startswith('/api/graph-runs/') and len([part for part in path.split('/') if part]) > 3 and [part for part in path.split('/') if part][3] in {
                'nodes', 'attempts', 'checkpoints', 'state-events', 'transitions', 'trace',
                'evaluations', 'metrics', 'interventions', 'joins', 'branches', 'waits', 'migrations',
            }:
                run_parts = [part for part in path.split('/') if part]
                run_id = run_parts[2] if len(run_parts) > 2 else ''
                collection = run_parts[3] if len(run_parts) > 3 else ''
                if collection in {
                    'nodes', 'attempts', 'checkpoints', 'state-events', 'transitions', 'trace',
                    'evaluations', 'metrics', 'interventions', 'joins', 'branches', 'waits', 'migrations',
                }:
                    limit = int(qs.get('limit', ['100'])[0])
                    if collection == 'nodes':
                        data = graph_runtime.list_node_runs(run_id, qs.get('status', [None])[0], limit)
                    elif collection == 'attempts':
                        data = graph_runtime.list_attempts(run_id, qs.get('node_run_id', [None])[0], limit)
                    elif collection == 'checkpoints':
                        data = graph_runtime.list_checkpoints(run_id, limit)
                    elif collection == 'state-events':
                        data = graph_runtime.list_state_events(run_id, limit)
                    elif collection == 'transitions':
                        data = graph_runtime.list_transitions(run_id, limit)
                    elif collection == 'trace':
                        data = graph_runtime.list_traces(run_id, qs.get('event_type', [None])[0], limit)
                    elif collection == 'evaluations':
                        data = graph_runtime.list_evaluations(run_id, limit)
                    elif collection == 'metrics':
                        data = graph_runtime.get_evaluation_metrics(run_id)
                    elif collection == 'interventions':
                        data = graph_runtime.list_interventions(run_id, limit)
                    elif collection == 'joins':
                        data = graph_runtime.list_join_states(run_id, limit)
                    elif collection == 'branches':
                        data = graph_runtime.list_branches(run_id, limit)
                    elif collection == 'waits':
                        data = graph_runtime.list_waits(run_id, limit)
                    else:
                        data = graph_runtime.list_migrations(run_id, limit)
                    self._send_json({'run_id': run_id, collection: data})
                    return
            elif path.startswith('/api/graph-runs/'):
                run_id = path.split('/')[3]
                run = graph_runtime.get_run(run_id)
                if not run:
                    self._send_error(404, 'Graph Run not found')
                    return
                run['ready'] = [dict(row) for row in graph_runtime.connection.execute_query(
                    "SELECT READY_ID, NODE_RUN_ID, NODE_KEY, STATUS, PRIORITY, AVAILABLE_AT FROM GRAPH_READY_NODES WHERE RUN_ID = :run_id ORDER BY CREATED_AT",
                    {'run_id': run_id})]
                self._send_json(run)
            elif path == '/api/graph/workers':
                self._send_json({'workers': [dict(row) for row in graph_runtime.connection.execute_query(
                    "SELECT WORKER_ID, AGENT_ID, RUNTIME, CAPABILITY_JSON, STATUS, LAST_HEARTBEAT_AT, NODE_ID, CREATED_AT FROM GRAPH_WORKERS ORDER BY LAST_HEARTBEAT_AT DESC FETCH FIRST :limit ROWS ONLY",
                    {'limit': max(1, min(int(qs.get('limit', ['100'])[0]), 500))})]})
            elif path == '/api/graph/events/inbox':
                self._send_json({'events': graph_event_api.pending_inbox(int(qs.get('limit', ['100'])[0]))})
            elif path == '/api/graph/events/dead-letter':
                self._send_json({'events': graph_event_api.dead_letters(int(qs.get('limit', ['100'])[0]))})
            elif path == '/api/graph/events/outbox':
                self._send_json({'events': graph_event_api.pending_outbox(int(qs.get('limit', ['100'])[0]))})
            elif path == '/api/graph-governance/events':
                self._send_json({'events': graph_runtime.list_governance_events(
                    run_id=qs.get('run_id', [None])[0], artifact_id=qs.get('artifact_id', [None])[0],
                    event_type=qs.get('event_type', [None])[0], limit=int(qs.get('limit', ['100'])[0]),
                )})
            elif path == '/api/graph/capabilities':
                self._send_json(graph_adapter.capability_probe())
            elif path == '/api/agents/registry':
                if self._require_admin() is None:
                    return
                self._send_json({'agents': agent_registration.list_registrations(limit=int(qs.get('limit', ['100'])[0]))})
            elif path == '/api/tasks':
                self._api_tasks()
            elif path == '/api/workspaces':
                self._api_workspaces(summary_only=qs.get('view', [''])[0].lower() == 'summary')
            elif path == '/api/specs':
                self._api_specs()
            elif path == '/api/sdd/changes':
                if self._require_admin() is None:
                    return
                self._send_json({'changes': [_clean_row(item) for item in sdd_api.list_changes(int(qs.get('limit', ['100'])[0]))]})
            elif path.startswith('/api/sdd/changes/'):
                if self._require_admin() is None:
                    return
                change_id = path.split('/')[4] if len(path.split('/')) > 4 else ''
                item = sdd_api.get_change(change_id)
                if not item:
                    self._send_error(404, 'SDD Change not found')
                    return
                self._send_json(_clean_row(item))
            elif path.startswith('/api/sdd/revisions/') and path.endswith('/graph'):
                if self._require_admin() is None:
                    return
                revision_id = path.split('/')[4]
                self._send_json(sdd_api.compile_execution_graph(revision_id))
            elif path == '/api/collab':
                self._api_collab()
            elif path == '/api/agent/skills':
                self._api_agent_discover_skills(qs)
            elif path == '/api/agent/deployment-check':
                self._api_agent_deployment_check()
            elif path.startswith('/api/agent/skill/') and path.endswith('/acquire'):
                self._api_agent_acquire_skill(path)
            elif path == '/api/skills':
                self._api_skills()
            elif path.startswith('/api/skill/'):
                self._handle_skill_get(path)
            elif path == '/api/stats':
                self._api_stats()
            elif path == '/api/admin/skill/list':
                self._handle_admin_skill_list()
            elif path.startswith('/api/admin/skill/') and path.endswith('/acquire'):
                self._handle_admin_skill_acquire()
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
            elif path == '/api/graph/causal':
                entity_id = qs.get('entity_id', [''])[0]
                depth = int(qs.get('depth', ['3'])[0])
                self._send_json({"causes": graph_api.find_causes(entity_id, depth), "contradictions": graph_api.find_contradictions(entity_id), "provenance": graph_api.trace_provenance(entity_id)})
            elif path == '/api/graph/collaboration':
                agent_id = qs.get('agent_id', [''])[0]
                group_id = qs.get('group_id', [''])[0]
                self._send_json({"trusted": graph_api.get_trusted_agents(agent_id, group_id), "recommendations": graph_api.recommend_collaborators(agent_id, group_id)})
            elif path == '/api/graph/lineage':
                entity_id = qs.get('entity_id', [''])[0]
                self._send_json(graph_api.trace_data_lineage(entity_id))
            elif path == '/api/graph/all':
                self._send_json(_graph_all())
            elif path == '/api/branches':
                self._api_branch_list(qs)
            elif path.startswith('/api/branch/tree/'):
                self._api_branch_tree(path)
            elif path.startswith('/api/branch/diff/'):
                self._api_branch_diff(path)
            elif path.startswith('/api/branch/') and path.endswith('/chain'):
                self._api_branch_chain(path, qs)
            elif path.startswith('/api/branch/') and path.endswith('/stats'):
                self._api_branch_stats(path)
            elif path.startswith('/api/branch/') and path.endswith('/spec'):
                self._api_branch_spec(path)
            elif path.startswith('/api/branch/') and path.endswith('/plans'):
                self._api_branch_plans(path)
            elif path.startswith('/api/branch/') and '/validate-spec/' in path:
                self._api_branch_validate_spec(path)
            elif path.startswith('/api/branch/') and path.endswith('/plans'):
                self._api_branch_plans(path)
            elif path == '/api/collab/group-branches' or path == '/api/collab/group-spec-validation':
                self._api_collab_branch(path, qs)
            elif path == '/api/loops':
                self._api_loops_list(qs)
            elif path.startswith('/api/loops/') and path.endswith('/stats'):
                self._api_loops_stats(path)
            elif path.startswith('/api/loops/') and path.endswith('/runs'):
                self._api_loops_runs(path, qs)
            elif path.startswith('/api/loops/') and path.endswith('/hooks'):
                self._api_loops_hooks(path)
            elif path.startswith('/api/loops/') and path.endswith('/children'):
                self._api_loops_children(path)
            elif path.startswith('/api/loops/') and path.endswith('/aggregation'):
                self._api_loops_aggregation(path)
            elif path.startswith('/api/loops/'):
                self._api_loops_get(path)
            elif path == '/api/loops/from-spec':
                self._api_loops_from_spec()
            elif path == '/api/loops/collab':
                self._api_loops_collab()
            elif path.startswith('/api/tasks/steps/') and path.endswith('/bind-loop'):
                self._api_task_step_bind_loop(path)
            elif path.startswith('/api/tasks/steps/') and path.endswith('/loop'):
                self._api_task_step_loop(path)
            elif path.startswith('/api/collab/') and path.endswith('/loop'):
                self._api_collab_loop(path)
            elif path.startswith('/api/branch/'):
                self._api_branch_get(path)
            elif path == '/api/audit':
                if self._require_governance_admin() is None:
                    return
                self._api_audit_list(qs)
            elif path == '/api/audit/stats':
                if self._require_governance_admin() is None:
                    return
                self._api_audit_stats(qs)
            elif path == '/api/approvals':
                if self._require_governance_admin() is None:
                    return
                self._api_approvals_list(qs)
            elif path == '/api/approvals/stats':
                if self._require_governance_admin() is None:
                    return
                self._api_approvals_stats(qs)
            elif path == '/api/governance/probe':
                if self._require_governance_admin() is None:
                    return
                self._send_json(governance_api.capability_probe())
            elif path == '/api/governance/resources':
                if self._require_governance_admin() is None:
                    return
                limit = max(1, min(int(qs.get('limit', ['100'])[0]), 500))
                self._send_json({'resources': [_clean_row(dict(item)) for item in governance_api.execute_query(
                    'SELECT RESOURCE_ID, RESOURCE_TYPE, OWNER_REF, CLASSIFICATION, ENVIRONMENT, STATUS, METADATA_JSON '
                    'FROM GOV_RESOURCES ORDER BY UPDATED_AT DESC FETCH FIRST :limit ROWS ONLY',
                    {'limit': limit})]})
            elif path == '/api/governance/policies':
                if self._require_governance_admin() is None:
                    return
                limit = max(1, min(int(qs.get('limit', ['100'])[0]), 500))
                self._send_json({'policies': [_clean_row(dict(item)) for item in governance_api.execute_query(
                    'SELECT POLICY_ID, RESOURCE_ID, SUBJECTS_JSON, ACTIONS_JSON, CLASSIFICATION, PURPOSE, '
                    'ENVIRONMENT, DECISION, REQUIRES_APPROVAL, POLICY_VERSION, STATUS, EFFECTIVE_AT, EXPIRES_AT '
                    'FROM GOV_POLICIES ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY',
                    {'limit': limit})]})
            elif path == '/api/governance/approvals':
                if self._require_governance_admin() is None:
                    return
                self._send_json({'approvals': governance_api.list_approvals(limit=int(qs.get('limit', ['100'])[0]), status=qs.get('status', [None])[0])})
            elif path == '/api/governance/audit':
                if self._require_governance_admin() is None:
                    return
                limit = max(1, min(int(qs.get('limit', ['100'])[0]), 1000))
                self._send_json({'events': [_clean_row(dict(item)) for item in governance_api.execute_query(
                    'SELECT AUDIT_ID, ACTOR_ID, ACTION, RESOURCE_ID, DECISION, REASON_CODE, POLICY_VERSION, '
                    'CORRELATION_ID, OUTCOME, AUDIT_LEVEL, DETAIL_JSON, PAYLOAD_HASH, CREATED_AT '
                    'FROM GOV_AUDIT_EVENTS ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY',
                    {'limit': limit})]})
            elif path == '/api/governance/emergency':
                if self._require_governance_admin() is None:
                    return
                limit = max(1, min(int(qs.get('limit', ['100'])[0]), 500))
                operations = governance_api.execute_query(
                    'SELECT OPERATION_ID, AGENT_ID, REQUESTED_BY, STATUS, REASON, IDEMPOTENCY_KEY, '
                    'CORRELATION_ID, CREATED_AT, UPDATED_AT FROM GOV_EMERGENCY_OPS '
                    'ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY', {'limit': limit}
                )
                for operation in operations:
                    operation['steps'] = governance_api.execute_query(
                        'SELECT STEP_ID, STEP_NAME, STATUS, OUTCOME, STARTED_AT, COMPLETED_AT '
                        'FROM GOV_EMERGENCY_STEPS WHERE OPERATION_ID = :operation_id ORDER BY STARTED_AT',
                        {'operation_id': operation.get('operation_id')}
                    )
                self._send_json({'operations': [_clean_row(dict(item)) for item in operations]})
            elif path == '/api/governance/evidence/export':
                principal = self._require_governance_admin()
                if principal is None:
                    return
                actor = principal['actor_id']
                self._send_json(governance_api.export_evidence(actor, limit=int(qs.get('limit', ['1000'])[0])))
            elif path == '/api/governance/grants':
                if self._require_governance_admin() is None:
                    return
                self._send_json({'grants': governance_api.list_grants(
                    limit=int(qs.get('limit', ['100'])[0]),
                    subject_id=qs.get('subject_id', [None])[0],
                    resource_id=qs.get('resource_id', [None])[0],
                    status=qs.get('status', [None])[0],
                )})
            elif path.startswith('/api/execution/jobs/'):
                self._handle_execution_job_get(path)
            elif path == '/ap/v1/agent/tasks':
                # Agent Protocol: list tasks
                from lib import task_plan_api
                plans = task_plan_api.list_plans()
                self._send_json([{"task_id": p.get("plan_id"), "input": p.get("goal", ""), "status": p.get("status", "")} for p in plans])
            elif path.startswith('/ap/v1/agent/tasks/') and path.endswith('/steps'):
                # Agent Protocol: list steps for a task
                from lib import task_plan_api
                parts = path.split('/')
                task_id = parts[-2]
                steps = task_plan_api.list_steps(task_id)
                self._send_json([{"step_id": s.get("step_id"), "status": s.get("status", "")} for s in steps])
            # v3.7.5 new routes
            elif path == '/api/collab/messages':
                self._api_messages_list(qs)
            elif path == '/api/collab/messages/inbox':
                self._api_messages_inbox(qs)
            elif path == '/api/collab/messages/unread':
                self._api_messages_unread(qs)
            elif path.startswith('/api/collab/messages/') and path.endswith('/thread'):
                self._api_messages_thread(path)
            elif path == '/api/orchestrator/status':
                self._api_orch_status(qs)
            elif path == '/api/monitor/overview':
                self._api_monitor_overview()
            elif path == '/api/monitor/agents':
                self._api_monitor_agents()
            elif path == '/api/monitor/stalls':
                self._api_monitor_stalls(qs)
            elif path == '/api/monitor/metrics':
                self._api_monitor_metrics(qs)
            elif path == '/api/monitor/alerts':
                self._api_monitor_alerts()
            elif path == '/api/traces':
                self._api_traces_list(qs)
            elif path.startswith('/api/traces/') and path.endswith('/tree'):
                self._api_traces_tree(path)
            elif path.startswith('/api/traces/') and path.endswith('/spans'):
                self._api_traces_spans(path, qs)
            elif path.startswith('/api/traces/'):
                self._api_traces_get(path)
            elif path == '/api/tools':
                self._api_tools_list(qs)
            elif path == '/api/tools/chains':
                self._api_tool_chains_list()
            elif path.startswith('/api/tools/') and '/import' not in path:
                self._api_tools_get(path)
            elif path == '/api/events/pending':
                self._api_events_pending(qs)
            elif path == '/api/events/subscriptions':
                self._api_events_subscriptions(qs)
            elif path == '/api/agents/discover':
                self._api_agents_discover(qs)
            else:
                self._send_error(404, 'API endpoint not found')
        except PermissionError as exc:
            self._send_error(403, str(exc))
        except ValueError as exc:
            self._send_error(422, str(exc))
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_execution_job_get(self, path):
        from lib import execution_control
        job_id = path.split('/')[-1]
        job = execution_control.get_job(job_id)
        if not job:
            self._send_error(404, 'Execution job not found')
            return
        session_data = _get_session(self)
        session = session_data[1] if session_data else {}
        if not _is_admin_role(session.get('role')) and job.get('agent_id') != session.get('agent_id'):
            self._send_error(403, 'Execution job belongs to another Agent')
            return
        self._send_json(_clean_row(job))

    def _handle_execution_job_action(self, path):
        from lib import execution_control
        parts = path.split('/')
        if len(parts) < 6:
            self._send_error(400, 'Invalid execution job action')
            return
        job_id, action = parts[-2], parts[-1]
        session_data = _get_session(self)
        session = session_data[1] if session_data else {}
        actor = session.get('username') or session.get('user_id') or 'admin'
        body = self._read_body()
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_error(400, 'Invalid JSON')
            return
        if action == 'approve':
            ok = execution_control.decide_job(job_id, True, actor, data.get('reason', ''))
        elif action == 'reject':
            ok = execution_control.decide_job(job_id, False, actor, data.get('reason', ''))
        elif action == 'cancel':
            ok = execution_control.cancel_job(job_id, actor)
        else:
            self._send_error(404, 'Unknown execution job action')
            return
        if not ok:
            self._send_error(409, 'Execution job state does not allow this action')
            return
        self._send_json(_clean_row(execution_control.get_job(job_id)))

    def _api_agents(self):
        agents = connection.execute_query(
            "SELECT agent_id, agent_name, agent_type, description, status, "
            "last_seen_at, created_at, updated_at FROM agent_registry ORDER BY created_at DESC"
        )
        sessions_list = agent_api.get_active_sessions()
        try:
            collaborations = connection.execute_query(
                "SELECT collab_id, source_agent_id, target_agent_id, col_type, entity_id, "
                "context, strength, status, created_at FROM agent_collaboration ORDER BY created_at DESC"
            )
        except Exception:
            collaborations = connection.execute_query(
                "SELECT col_id AS collab_id, source_agent_id, target_agent_id, col_type, entity_id, "
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

    def _api_workspaces(self, summary_only=False):
        if summary_only:
            workspaces = connection.execute_query(
                "SELECT workspace_id, workspace_name, status, updated_at "
                "FROM workspaces ORDER BY updated_at DESC"
            )
            self._send_json({'workspaces': [_clean_row(w) for w in workspaces]})
            return
        workspaces = connection.execute_query(
            "SELECT workspace_id, owner_user_id, workspace_name, workspace_type, "
            "isolation_mode, current_agent_id, current_session_id, summary, status, "
            "created_at, updated_at FROM workspaces ORDER BY updated_at DESC"
        )
        for ws in workspaces:
            ctx_count = connection.execute_query_one(
                "SELECT COUNT(*) AS cnt FROM workspace_context WHERE workspace_id = :wsid",
                {"wsid": ws['workspace_id']}
            )
            ws['context_count'] = ctx_count['cnt'] if ctx_count else 0
            br_count = connection.execute_query_one(
                "SELECT COUNT(*) AS cnt FROM context_branches WHERE workspace_id = :wsid",
                {"wsid": ws['workspace_id']}
            )
            ws['branch_count'] = br_count['cnt'] if br_count else 0
            ctx_chain = connection.execute_query(
                "SELECT context_id, context_type, agent_id, context_data, parent_context_id, created_at "
                "FROM workspace_context WHERE workspace_id = :wsid ORDER BY created_at DESC",
                {"wsid": ws['workspace_id']}
            )
            ws['context_chain'] = [_clean_row(c) for c in ctx_chain]
            linked = connection.execute_query(
                "SELECT wt.plan_id, tp.goal, tp.status FROM workspace_tasks wt "
                "JOIN task_plans tp ON wt.plan_id = tp.plan_id "
                "WHERE wt.workspace_id = :wsid",
                {"wsid": ws['workspace_id']}
            )
            ws['linked_tasks'] = [_clean_row(t) for t in linked]
            ws['task_count'] = len(linked)
        self._send_json({'workspaces': [_clean_row(w) for w in workspaces]})

    def _api_specs(self):
        specs = spec_api.list_specs(limit=100)
        for sp in specs:
            sp['plan_links'] = spec_api.get_spec_plan_links(sp['entity_id'])
        self._send_json({'specs': [_clean_row(s) for s in specs]})

    def _handle_sdd_post(self, path):
        """Native SDD write routes.  Each operation is database-authoritative."""
        if self._require_admin() is None:
            return
        try:
            data = json.loads(self._read_body() or b'{}')
            if not isinstance(data, dict):
                raise ValueError('JSON object required')
            actor = self._authenticated_actor()
            if path == '/api/sdd/changes':
                result = sdd_api.create_change(data.get('title', ''), summary=str(data.get('summary') or ''),
                                               scope=str(data.get('profile_key') or 'SOFTWARE_DELIVERY'),
                                               security_domain_id=data.get('security_domain_id'), actor=actor)
            elif path.startswith('/api/sdd/revisions/') and path.endswith('/clauses'):
                revision_id = path.split('/')[4]
                result = sdd_api.create_clause(revision_id, str(data.get('kind') or 'REQUIREMENT'), str(data.get('title') or ''),
                                               body_text=str(data.get('body_text') or ''), structured=data.get('structured'),
                                               ordinal=int(data.get('ordinal') or 0), actor=actor)
            elif path.startswith('/api/sdd/clauses/') and path.endswith('/patch'):
                clause_id = path.split('/')[4]
                result = sdd_api.patch_clause(clause_id, expected_version=int(data.get('expected_version')),
                                              title=data.get('title'), body_text=data.get('body_text'), structured=data.get('structured'),
                                              reason=str(data.get('reason') or ''), actor=actor)
            elif path.startswith('/api/sdd/revisions/') and path.endswith('/baseline'):
                revision_id = path.split('/')[4]
                result = sdd_api.approve_baseline(revision_id, reason=str(data.get('reason') or ''), actor=actor,
                                                  approvals_complete=bool(data.get('approvals_complete', True)),
                                                  reviews_complete=bool(data.get('reviews_complete', True)))
            elif path.startswith('/api/sdd/revisions/') and path.endswith('/working-revision'):
                revision_id = path.split('/')[4]
                revision = sdd_api.get_revision(revision_id)
                if not revision:
                    raise ValueError('revision not found')
                result = sdd_api.create_working_revision(str(revision['change_id']), reason=str(data.get('reason') or ''), actor=actor)
            elif path.startswith('/api/sdd/revisions/') and path.endswith('/tasks'):
                revision_id = path.split('/')[4]
                result = sdd_api.create_task(revision_id, str(data.get('title') or ''), role_key=str(data.get('role_key') or ''),
                                             risk_level=str(data.get('risk_level') or 'LOW'), read_set=data.get('read_set') or [],
                                             write_set=data.get('write_set') or [], depends_on=data.get('depends_on') or [], actor=actor)
            elif path.startswith('/api/sdd/revisions/') and path.endswith('/runs'):
                revision_id = path.split('/')[4]
                result = sdd_api.create_run(revision_id, budget=data.get('budget') or {}, actor=actor)
            elif path == '/api/sdd/evidence':
                result = sdd_api.record_evidence(str(data.get('revision_id') or ''), task_id=data.get('task_id'),
                                                  criterion_clause_id=data.get('criterion_clause_id'), evidence_type=str(data.get('evidence_type') or 'TEST'),
                                                  source_kind=str(data.get('source_kind') or 'WORKER'), reference_uri=str(data.get('reference_uri') or ''),
                                                  artifact_digest=str(data.get('artifact_digest') or ''), detail=data.get('detail') or {}, actor=actor,
                                                  independent=bool(data.get('independent')))
            elif path == '/api/sdd/scm':
                result = scm_adapter_api.register_connection(str(data.get('adapter_kind') or ''), str(data.get('repository_ref') or ''),
                                                             credential_reference=data.get('credential_reference'), policy=data.get('policy') or {}, actor=actor)
            else:
                self._send_error(404, 'SDD route not found')
                return
            self._send_json(_clean_row(result), 201)
        except (ValueError, PermissionError) as exc:
            self._send_error(422, str(exc))

    def _api_collab(self):
        groups = connection.execute_query(
            "SELECT g.group_id, g.group_name, g.group_type, g.description, "
            "g.workspace_id, g.coordinator_agent_id, g.sharing_policy, g.status, "
            "g.metadata, g.created_at, g.updated_at, g.branch_id, g.spec_id, "
            "(SELECT COUNT(*) FROM collab_group_members cgm WHERE cgm.group_id = g.group_id AND cgm.status = 'ACTIVE') AS member_count "
            "FROM collab_groups g ORDER BY g.updated_at DESC"
        )
        for g in groups:
            members = connection.execute_query(
                "SELECT member_id, agent_id, role, personal_workspace_id, joined_at, status "
                "FROM collab_group_members WHERE group_id = :gid ORDER BY joined_at",
                {"gid": g['group_id']}
            )
            g['members'] = [_clean_row(m) for m in members]
        self._send_json({'groups': [_clean_row(g) for g in groups]})

    def _api_skills(self):
        from lib import skill_api
        skills = skill_api.list_skills(limit=200)
        self._send_json({'skills': [_clean_row(s) for s in skills]})

    def _api_agent_deployment_check(self):
        from lib import deploy_api
        result = deploy_api.check_deployment()
        self._send_json(result)

    def _api_agent_discover_skills(self, qs):
        from lib import skill_acquire_api
        keyword = qs.get('keyword', [None])[0] or qs.get('q', [None])[0]
        skill_type = qs.get('type', [None])[0]
        runtime = qs.get('runtime', [None])[0]
        skill_format = qs.get('format', [None])[0]
        results = skill_acquire_api.discover_skills(
            skill_type=skill_type, runtime=runtime,
            skill_format=skill_format, keyword=keyword,
        )
        self._send_json({'skills': [_clean_row(r) for r in results]})

    def _api_agent_acquire_skill(self, path):
        parts = path.split('/')
        if len(parts) < 6:
            self._send_error(400, 'Invalid skill acquire path')
            return
        skill_id = parts[4]
        from lib import skill_acquire_api
        result = skill_acquire_api.acquire_skill_text(skill_id)
        if result is None:
            self._send_error(404, 'Skill not found or not active')
            return
        self._send_json(_clean_row(result))

    def _handle_skill_get(self, path):
        if self._require_auth() is None:
            return
        from lib import skill_api, skill_storage
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid skill path')
            return
        skill_id = parts[3]
        if len(parts) == 4:
            skill = skill_api.get_skill(skill_id)
            if skill is None:
                self._send_error(404, 'Skill not found')
                return
            self._send_json(_clean_row(skill))
            return
        action = parts[4] if len(parts) > 4 else ''
        if action == 'resource':
            skill = skill_api.get_skill(skill_id)
            if skill is None:
                self._send_error(404, 'Skill not found')
                return
            if not skill.get('resource_uri'):
                self._send_error(404, 'No resource attached')
                return
            from lib import skill_storage
            content = skill_storage.read_resource_content(skill_id)
            if content is None:
                self._send_error(404, 'Resource file not found')
                return
            skill_name = skill.get('skill_name', 'skill')
            skill_version = skill.get('skill_version', '1.0.0')
            fname = f"{skill_name}-{skill_version}.zip"
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        self._send_error(404, 'Unknown skill action')

    def _handle_skill_post(self, path):
        if self._require_auth() is None:
            return
        from lib import skill_api
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid skill path')
            return
        skill_id = parts[3]
        action = parts[4] if len(parts) > 4 else ''
        if action == 'upload':
            self._handle_skill_upload(skill_id)
        elif action == 'update':
            self._handle_skill_update(skill_id)
        elif action == 'delete':
            self._handle_skill_delete(skill_id)
        else:
            self._send_error(404, 'Unknown skill action')

    def _handle_skill_create(self, data):
        from lib import skill_api
        skill_id = skill_api.register_skill(
            title=data.get('title', ''),
            skill_name=data.get('skill_name', ''),
            skill_version=data.get('skill_version', '1.0.0'),
            skill_type=data.get('skill_type', 'CUSTOM'),
            skill_format=data.get('skill_format', 'TEXT'),
            text_content=data.get('text_content'),
            runtime=data.get('runtime', 'PYTHON'),
            parameters=data.get('parameters'),
            dependencies=data.get('dependencies'),
            category=data.get('category'),
            owned_by_agent=data.get('owned_by_agent'),
            visibility=data.get('visibility', 'SHARED'),
        )
        return skill_id

    def _handle_skill_create_route(self):
        if self._require_auth() is None:
            return
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self._send_error(400, 'multipart/form-data required. Upload a zip containing SKILL.md')
            return
        boundary = content_type.split('boundary=')[-1].encode()
        body = self._read_body()
        if not body:
            self._send_error(400, 'Empty body')
            return
        file_content = None
        filename = None
        parts_list = body.split(b'--' + boundary)
        for part in parts_list:
            if part in (b'', b'--\r\n', b'--', b'--\r\n\r\n'):
                continue
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                continue
            headers_raw = part[:header_end].decode('utf-8', errors='replace')
            part_body = part[header_end + 4:]
            if part_body.endswith(b'\r\n'):
                part_body = part_body[:-2]
            if 'filename=' in headers_raw:
                for h in headers_raw.split('\r\n'):
                    if 'filename=' in h:
                        for seg in h.split(';'):
                            seg = seg.strip()
                            if seg.startswith('filename='):
                                filename = seg.split('=', 1)[1].strip('" ')
                file_content = part_body
        if file_content is None or not filename:
            self._send_error(400, 'No file uploaded')
            return
        try:
            from lib.skill_parser import parse_skill_package
            from lib.skill_storage import save_resource_files
            from lib import skill_api
            meta, resource_files = parse_skill_package(file_content)
            skill_id = skill_api.register_skill(
                title=meta['title'],
                skill_name=meta['skill_name'],
                skill_version=meta['skill_version'],
                skill_type=meta['skill_type'],
                skill_format=meta['skill_format'],
                text_content=meta.get('text_content'),
                resource_checksum=meta.get('package_checksum'),
                skill_description=meta.get('skill_description'),
                runtime=meta['runtime'],
                parameters=meta.get('parameters'),
                dependencies=meta.get('dependencies'),
                category=meta.get('category'),
                owned_by_agent=meta.get('owned_by_agent'),
                visibility=meta.get('visibility', 'SHARED'),
            )
            if resource_files:
                save_resource_files(skill_id, resource_files)
            skill = skill_api.get_skill(skill_id)
            self._send_json({'success': True, 'skill_id': skill_id, 'skill': _clean_row(skill), 'file_count': len(resource_files)})
        except ValueError as e:
            self._send_error(400, str(e))
        except Exception as e:
            self._send_error(500, 'Failed to parse skill package: {}'.format(str(e)))
    def _handle_skill_upload(self, skill_id):
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self._send_error(400, 'multipart/form-data required')
            return
        boundary = content_type.split('boundary=')[-1].encode()
        body = self._read_body()
        if not body:
            self._send_error(400, 'Empty body')
            return
        parts_list = body.split(b'--' + boundary)
        file_content = None
        filename = 'resource'
        for part in parts_list:
            if part in (b'', b'--\r\n', b'--', b'--\r\n\r\n'):
                continue
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                continue
            headers_raw = part[:header_end].decode('utf-8', errors='replace')
            part_body = part[header_end + 4:]
            if part_body.endswith(b'\r\n'):
                part_body = part_body[:-2]
            if 'filename=' in headers_raw:
                for h in headers_raw.split('\r\n'):
                    if 'filename=' in h:
                        for seg in h.split(';'):
                            seg = seg.strip()
                            if seg.startswith('filename='):
                                filename = seg.split('=', 1)[1].strip('" ')
                file_content = part_body
        if file_content is None:
            self._send_error(400, 'No file found in upload')
            return
        from lib import skill_api
        result = skill_api.upload_skill_resource(skill_id, filename, file_content)
        if result is None:
            self._send_error(404, 'Skill not found')
            return
        self._send_json({'success': True, 'resource': result})

    def _handle_skill_update(self, skill_id):
        body = self._read_body()
        try:
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        from lib import skill_api
        success = skill_api.update_skill(skill_id, **data)
        self._send_json({'success': success})

    def _handle_skill_delete(self, skill_id):
        from lib import skill_api
        success = skill_api.delete_skill(skill_id)
        self._send_json({'success': success})

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
        skill_row = connection.execute_query_one("SELECT COUNT(*) AS cnt FROM entities WHERE entity_type = 'SKILL'")
        try:
            audit_row = connection.execute_query_one("SELECT COUNT(*) AS cnt FROM context_audit_log WHERE resolution_status = 'OPEN'")
        except Exception:
            audit_row = None
        try:
            active_branches_row = connection.execute_query_one(
                "SELECT COUNT(*) AS c FROM context_branches WHERE status='ACTIVE'"
            )
        except Exception:
            active_branches_row = connection.execute_query_one(
                "SELECT COUNT(*) AS c FROM context_branches WHERE branch_status='ACTIVE'"
            )
        try:
            total_branches_row = connection.execute_query_one("SELECT COUNT(*) AS c FROM context_branches")
        except Exception:
            total_branches_row = {'c': 0}
        self._send_json({
            'entity_counts': entity_counts,
            'edge_count': edge_row['cnt'] if edge_row else 0,
            'workspace_count': ws_row['cnt'] if ws_row else 0,
            'agent_count': agent_row['cnt'] if agent_row else 0,
            'spec_count': spec_row['cnt'] if spec_row else 0,
            'collab_count': collab_row['cnt'] if collab_row else 0,
            'skill_count': skill_row['cnt'] if skill_row else 0,
            'audit_open_count': audit_row['cnt'] if audit_row else 0,
            'active_branches': active_branches_row['c'] if active_branches_row else 0,
            'total_branches': total_branches_row['c'] if total_branches_row else 0,
        })

    def _api_branch_list(self, qs):
        workspace_id = qs.get('workspace_id', [None])[0]
        agent_id = qs.get('agent_id', [None])[0]
        status = qs.get('status', [None])[0]
        branch_type = qs.get('branch_type', [None])[0]
        result = branch_api.list_branches(
            workspace_id=workspace_id, agent_id=agent_id,
            status=status, branch_type=branch_type,
        )
        self._send_json({'branches': [_clean_row(b) for b in result]})

    def _api_branch_get(self, path):
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        result = branch_api.get_branch(branch_id)
        if result is None:
            self._send_error(404, 'Branch not found')
            return
        self._send_json(_clean_row(result))

    def _api_branch_chain(self, path, qs):
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        limit = qs.get('limit', [None])[0]
        limit = int(limit) if limit else None
        result = branch_api.get_branch_context_chain(branch_id, limit=limit)
        self._send_json({'chain': [_clean_row(c) for c in result]})

    def _api_branch_stats(self, path):
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        result = branch_api.get_branch_stats(branch_id)
        if result is None:
            self._send_error(404, 'Branch not found')
            return
        self._send_json(_clean_row(result))

    def _api_branch_tree(self, path):
        parts = path.split('/')
        if len(parts) < 5:
            self._send_error(400, 'Invalid branch tree path')
            return
        workspace_id = parts[4]
        result = branch_api.get_branch_tree(workspace_id)
        self._send_json(_clean_row(result))

    def _api_branch_diff(self, path):
        parts = path.split('/')
        if len(parts) < 6:
            self._send_error(400, 'Invalid branch diff path')
            return
        branch_a_id = parts[4]
        branch_b_id = parts[5]
        result = branch_api.diff_branches(branch_a_id, branch_b_id)
        self._send_json(_clean_row(result))

    def _api_branch_fork(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        result = branch_api.fork_branch(
            workspace_id=data.get('workspace_id'),
            fork_context_id=data.get('fork_context_id'),
            branch_name=data.get('branch_name'),
            branch_type=data.get('branch_type'),
            agent_id=data.get('agent_id'),
            source_agent_id=data.get('source_agent_id'),
            purpose=data.get('purpose'),
            fork_session_id=data.get('fork_session_id'),
        )
        if isinstance(result, str):
            self._send_json({'branch_id': result, 'success': True})
        else:
            self._send_json(_clean_row(result))

    def _api_branch_merge(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        result = branch_api.merge_branch(
            source_branch_id=data.get('source_branch_id'),
            target_branch_id=data.get('target_branch_id'),
            merge_type=data.get('merge_type'),
            merged_by_agent=data.get('merged_by_agent'),
            conflict_resolutions=data.get('conflict_resolutions'),
        )
        self._send_json(_clean_row(result))

    def _api_branch_abandon(self, path):
        if self._require_auth() is None:
            return
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        result = branch_api.abandon_branch(branch_id, reason=data.get('reason'))
        self._send_json({'success': bool(result), 'branch_id': branch_id, 'branch_status': 'ABANDONED'})

    def _api_branch_pause(self, path):
        if self._require_auth() is None:
            return
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        result = branch_api.pause_branch(branch_id)
        self._send_json({'success': bool(result), 'branch_id': branch_id, 'branch_status': 'PAUSED'})

    def _api_branch_resume(self, path):
        if self._require_auth() is None:
            return
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        result = branch_api.resume_branch(branch_id)
        self._send_json({'success': bool(result), 'branch_id': branch_id, 'branch_status': 'ACTIVE'})

    def _api_branch_lesson(self, path):
        if self._require_auth() is None:
            return
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        result = branch_api.mark_as_lesson(
            branch_id=branch_id,
            context_id=data.get('context_id'),
            lesson_type=data.get('lesson_type'),
            lesson_summary=data.get('lesson_summary'),
            lesson_detail=data.get('lesson_detail'),
            agent_id=data.get('agent_id'),
        )
        if isinstance(result, dict):
            self._send_json(_clean_row(result))
        else:
            self._send_json({'success': True, 'branch_id': branch_id})

    def _api_branch_extract_lessons(self, path):
        if self._require_auth() is None:
            return
        parts = path.split('/')
        if len(parts) < 4:
            self._send_error(400, 'Invalid branch path')
            return
        branch_id = parts[3]
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        result = branch_api.extract_lessons_from_branch(branch_id, auto_confirm=data.get('auto_confirm', False))
        self._send_json({'lessons': [_clean_row(l) for l in result]})

    def _api_branch_spec(self, path):
        if self._require_auth() is None:
            return
        try:
            branch_id = path.split('/api/branch/')[1].replace('/spec', '')
            if not branch_id:
                self._send_error(400, 'Branch ID required')
                return
            from lib import spec_api
            from lib.connection import execute_query
            specs = execute_query(
                'SELECT S.ENTITY_ID, E.TITLE, S.SPEC_STATUS FROM SPEC_META S JOIN ENTITIES E ON S.ENTITY_ID=E.ENTITY_ID AND S.ENTITY_TYPE=E.ENTITY_TYPE WHERE S.BRANCH_ID = :vbid',
                {'vbid': branch_id}
            )
            self._send_json([_clean_row(r) for r in specs])
        except Exception as e:
            self._send_error(500, str(e))

    def _api_branch_plans(self, path):
        if self._require_auth() is None:
            return
        parts = path.split('/')
        branch_id = parts[3] if len(parts) > 3 else None
        if not branch_id:
            self._send_error(400, 'Branch ID required')
            return
        result = task_plan_api.get_branch_plans(branch_id)
        self._send_json([_clean_row(r) for r in result])

    def _api_branch_validate_spec(self, path):
        if self._require_auth() is None:
            return
        parts = path.split('/')
        branch_id = parts[3] if len(parts) > 3 else None
        spec_id = parts[5] if len(parts) > 5 else None
        if not branch_id or not spec_id:
            self._send_error(400, 'Branch ID and Spec ID required')
            return
        try:
            from lib import spec_api
            result = spec_api.validate_branch_against_spec(branch_id, spec_id)
            self._send_json(result)
        except Exception as e:
            self._send_error(500, str(e))

    def _api_branch_fork_for_spec(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            from lib import branch_api
            result = branch_api.fork_branch_for_spec(
                workspace_id=data.get('workspace_id'),
                spec_id=data.get('spec_id'),
                branch_name=data.get('branch_name'),
                agent_id=data.get('agent_id'),
                source_agent_id=data.get('source_agent_id'),
            )
            self._send_json({'branch_id': result, 'success': True})
        except Exception as e:
            self._send_error(500, str(e))

    def _api_branch_merge_with_validation(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            from lib import branch_api
            result = branch_api.merge_branch_with_validation(
                source_branch_id=data.get('source_branch_id'),
                target_branch_id=data.get('target_branch_id'),
                spec_id=data.get('spec_id'),
                merged_by_agent=data.get('merged_by_agent'),
                conflict_resolutions=data.get('conflict_resolutions'),
            )
            self._send_json(result)
        except Exception as e:
            self._send_error(500, str(e))

    def _api_collab_branch(self, path, qs):
        if self._require_auth() is None:
            return
        try:
            from lib import collab_api
            if path.endswith('group-branches'):
                group_id = qs.get('group_id', [None])[0]
                if not group_id:
                    self._send_error(400, 'group_id required')
                    return
                result = collab_api.get_member_branches(group_id)
                self._send_json([_clean_row(r) for r in result])
            elif path.endswith('group-spec-validation'):
                group_id = qs.get('group_id', [None])[0]
                spec_id = qs.get('spec_id', [None])[0]
                if not group_id:
                    self._send_error(400, 'group_id required')
                    return
                result = collab_api.validate_group_against_spec(group_id, spec_id)
                self._send_json(result)
        except Exception as e:
            self._send_error(500, str(e))

    def _api_branch_fork_parallel(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            from lib import branch_api
            agent_ids = data.get('agent_ids', [])
            if not agent_ids:
                self._send_error(400, 'agent_ids required')
                return
            result = branch_api.fork_parallel_branches(
                workspace_id=data.get('workspace_id'),
                agent_ids=agent_ids,
                branch_name_prefix=data.get('branch_name_prefix', 'parallel'),
                spec_id=data.get('spec_id'),
                purpose=data.get('purpose'),
            )
            self._send_json(result)
        except Exception as e:
            self._send_error(500, str(e))

    def _api_branch_merge_parallel(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            from lib import branch_api
            result = branch_api.merge_parallel_branches(
                source_branch_ids=data.get('source_branch_ids', []),
                target_branch_id=data.get('target_branch_id'),
                merged_by_agent=data.get('merged_by_agent'),
            )
            self._send_json(result)
        except Exception as e:
            self._send_error(500, str(e))

    def _api_collab_distribute_plan(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            from lib import task_plan_api
            result = task_plan_api.distribute_plan_to_group(
                plan_id=data.get('plan_id'),
                group_id=data.get('group_id'),
            )
            self._send_json(result)
        except Exception as e:
            self._send_error(500, str(e))

    def _api_collab_sync_context(self):
        if self._require_auth() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_error(400, 'Invalid JSON')
            return
        try:
            from lib import collab_api
            result = collab_api.sync_group_context(data.get('group_id'))
            self._send_json(result)
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_portal_register(self):
        try:
            connection.set_agent_context(None)
            body = self._read_body()
            data = json.loads(body)
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
            if not username or not password or len(username) < 3 or len(password) < 6:
                self._send_json({'success': False, 'error': 'Username min 3 chars, password min 6 chars'}, 400)
                return
            db_exists = connection.execute_query_one(
                "SELECT USER_ID, AUTH_SOURCE FROM SYSTEM_USERS WHERE UPPER(USERNAME) = UPPER(:v_uname)",
                {"v_uname": username},
            )
            if db_exists:
                if db_exists.get('auth_source') == 'LDAP':
                    self._send_json({'success': False, 'error': 'This username belongs to an LDAP user, please use LDAP login'}, 409)
                else:
                    self._send_json({'success': False, 'error': 'Username already exists'}, 409)
                return
            result = user_api.register_user(username, password)
            if not result:
                self._send_json({'success': False, 'error': 'Username already exists'}, 409)
                return
            if str(result.get('status') or '').upper() == 'PENDING':
                self._send_json({
                    'success': True,
                    'status': 'PENDING',
                    'request_id': result.get('request_id'),
                    'username': username,
                    'message': 'Registration submitted for approval',
                }, 202)
                return
            session_id = _create_session(result['username'], result['user_id'], result['role'])
            sess = sessions[session_id]
            portal_agent = _get_or_assign_portal_agent(result['user_id'])
            if portal_agent:
                sess['agent_id'] = portal_agent['agent_id']
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', _session_cookie(session_id))
            body_out = json.dumps({'success': True, 'session_id': session_id, 'user_id': result['user_id'], 'username': result['username'], 'has_agent': bool(portal_agent)}).encode()
            self.send_header('Content-Length', str(len(body_out)))
            self.end_headers()
            self.wfile.write(body_out)
        except Exception as e:
            self._send_json({'success': False, 'error': str(e)}, 500)

    def _handle_portal_login(self):
        try:
            body = self._read_body()
            data = json.loads(body)
            username = data.get('username', '').strip()
            password = str(data.get('password', '') or '')
            mfa_code = str(data.get('mfa_code', '') or '').strip()
        except Exception:
            self._send_json({'success': False, 'error': 'Invalid request'}, 400)
            return

        if not username or not password:
            self._send_json({'success': False, 'error': 'Invalid username or password'}, 401)
            return

        try:
            if security_lifecycle.is_login_locked(username):
                self._send_json({'success': False, 'error': 'Invalid username or password'}, 401)
                return
            # Portal must use the same Principal-based verifier as Dashboard.
            # Falling back to SYSTEM_USERS here would bypass lockout, MFA, and
            # permission-version checks for an otherwise valid legacy account.
            user = identity_api.authenticate_local(username, password)
        except Exception:
            logger.exception('Portal identity authentication failed')
            self._send_json({'success': False, 'error': 'Identity service unavailable'}, 503)
            return
        if not user or not user.get('principal_id'):
            try:
                security_lifecycle.record_login_failure(username)
            except Exception:
                pass
            self._send_json({'success': False, 'error': 'Invalid username or password'}, 401)
            return

        try:
            principal_id = str(user['principal_id'])
            if not identity_api.entry_allowed(principal_id, 'PORTAL'):
                self._send_json({'success': False, 'error': 'Portal access is disabled'}, 403)
                return
            required = security_lifecycle.mfa_required(principal_id)
            method = security_lifecycle.verify_mfa(principal_id, mfa_code) if mfa_code else ''
            if required and not method and not security_lifecycle.has_active_mfa_factor(principal_id):
                # Password is valid, but this first-use administrator session is
                # restricted to the MFA enrollment endpoints.
                security_lifecycle.record_login_success(principal_id)
                session_id = _create_session(
                    user['username'], str(user['user_id']), user.get('role', 'user'),
                    mfa_level='SETUP', require_identity=True,
                )
                sess = sessions[session_id]
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', _session_cookie(session_id))
                body_out = json.dumps({
                    'success': True,
                    'session_id': session_id,
                    'user_id': str(user['user_id']),
                    'username': user['username'],
                    'mfa_level': 'SETUP',
                    'mfa_setup_required': True,
                    'csrf_token': sess.get('csrf_token', ''),
                    'expires_at': sess.get('expires_at', ''),
                    'session_timeout_seconds': _session_timeout(),
                }).encode()
                self.send_header('Content-Length', str(len(body_out)))
                self.end_headers()
                self.wfile.write(body_out)
                return

            admission = governed_contracts.mfa_admission_decision(
                principal_active=True,
                required=required,
                level='STRONG' if method else 'NONE',
                accepted=bool(method),
                method=method,
            )
            if not admission.allowed:
                try:
                    security_lifecycle.record_login_failure(username)
                except Exception:
                    pass
                self._send_json({'success': False, 'error': 'MFA verification required'}, 401)
                return
            mfa_level = 'STRONG' if method else 'NONE'
            security_lifecycle.record_login_success(principal_id)
        except Exception:
            logger.exception('Portal MFA admission failed')
            self._send_json({'success': False, 'error': 'MFA service unavailable'}, 503)
            return

        session_id = _create_session(
            user['username'], str(user['user_id']), user.get('role', 'user'),
            mfa_level=mfa_level, require_identity=True,
        )
        sess = sessions[session_id]
        portal_agent = _get_or_assign_portal_agent(str(user['user_id']))
        if portal_agent:
            sess['agent_id'] = portal_agent['agent_id']
        # Auto-load most recent conversation workspace, or create one if none exists
        try:
            recent_ws = connection.execute_query_one(
                "SELECT WORKSPACE_ID FROM WORKSPACES WHERE OWNER_USER_ID = :v_uid AND WORKSPACE_TYPE = 'CONVERSATION' AND STATUS = 'ACTIVE' ORDER BY CREATED_AT DESC",
                {"v_uid": str(user['user_id'])},
            )
            if recent_ws:
                sess['workspace_id'] = recent_ws['workspace_id']
                try:
                    if portal_agent:
                        agent_session = agent_api.create_session(
                            portal_agent['agent_id'], owner_user_id=str(user['user_id'])
                        )
                        sess['agent_session_id'] = agent_session
                except Exception:
                    pass
            else:
                ws = workspace_api.create_workspace(owner_user_id=str(user['user_id']), name='New Chat', workspace_type='CONVERSATION')
                sess['workspace_id'] = ws
        except Exception:
            pass
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', _session_cookie(session_id))
        body_out = json.dumps({
            'success': True,
            'session_id': session_id,
            'user_id': str(user['user_id']),
            'username': user['username'],
            'has_agent': bool(portal_agent),
            'mfa_level': mfa_level,
            'mfa_setup_required': False,
            'csrf_token': sess.get('csrf_token', ''),
            'expires_at': sess.get('expires_at', ''),
            'session_timeout_seconds': _session_timeout(),
        }).encode()
        self.send_header('Content-Length', str(len(body_out)))
        self.end_headers()
        self.wfile.write(body_out)

    def _handle_admin_agent_register(self):
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_json({'error': 'Invalid request body'}, 400)
            return
        agent_id = data.get('agent_id', '')
        agent_name = data.get('agent_name', '')
        admin_token = data.get('admin_token', '')
        if not agent_id or not agent_name or not admin_token:
            self._send_json({'error': 'agent_id, agent_name, and admin_token are required'}, 400)
            return
        try:
            result = agent_api.register_agent_via_admin(
                agent_id=agent_id,
                agent_name=agent_name,
                admin_token=admin_token,
                agent_type=data.get('agent_type'),
                description=data.get('description'),
                capabilities=data.get('capabilities'),
                config=data.get('config'),
            )
            if result is None:
                self._send_json({'error': 'Admin token verification failed'}, 403)
                return
            if edition_features.has_feature('governance'):
                try:
                    registration = agent_registration.register_agent(
                        agent_id=agent_id,
                        owner_ref=data.get('owner_ref') or 'administrator',
                        runtime=data.get('runtime') or data.get('agent_type') or 'generic',
                        environment=data.get('environment') or 'managed',
                        node_id=data.get('node_id') or '',
                        capabilities=data.get('capabilities') or [],
                        credential_version='1', created_by='admin-token',
                        idempotency_key=data.get('idempotency_key'),
                    )
                    if registration:
                        result['platform_registration'] = {
                            'agent_id': registration.get('agent_id'),
                            'status': registration.get('status'),
                            'credential': registration.get('credential'),
                            'credential_version': registration.get('credential_version'),
                        }
                except Exception as registration_error:
                    logger.warning('Platform Agent registration was not persisted: %s', registration_error)
            self._send_json(result)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_agent_recover(self):
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            self._send_json({'error': 'Invalid request body'}, 400)
            return
        agent_id = data.get('agent_id', '')
        recovery_code = data.get('recovery_code', '')
        admin_token = data.get('admin_token', '')
        if not agent_id or not recovery_code or not admin_token:
            self._send_json({'error': 'agent_id, recovery_code, and admin_token are required'}, 400)
            return
        try:
            result = agent_api.recover_agent_via_admin(
                agent_id=agent_id,
                recovery_code=recovery_code,
                admin_token=admin_token,
            )
            if result is None:
                self._send_json({'error': 'Recovery failed: invalid token, wrong recovery code, or agent still active'}, 403)
                return
            self._send_json(result)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_token_generate(self):
        if self._require_admin() is None:
            return
        try:
            token = agent_api.generate_admin_token()
            self._send_json({'admin_token': token})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_token_rotate(self):
        if self._require_admin() is None:
            return
        try:
            token = agent_api.generate_admin_token()
            self._send_json({'admin_token': token})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_crypto_rotate_all(self):
        if not self._is_admin_session():
            self._send_error(403, 'Admin session required')
            return
        try:
            from lib.agent_api import rotate_all_crypto_keys
            results = rotate_all_crypto_keys()
            self._send_json({'rotated': results, 'count': len(results)})
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_admin_crypto_rotate_agent(self, agent_id):
        if not self._is_admin_session():
            self._send_error(403, 'Admin session required')
            return
        try:
            from lib.agent_api import rotate_agent_crypto_key
            result = rotate_agent_crypto_key(agent_id)
            if result:
                self._send_json(result)
            else:
                self._send_error(404, 'Agent not found: ' + agent_id)
        except Exception as e:
            self._send_error(500, str(e))

    def _handle_admin_skill_list(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        admin_token = self.headers.get('X-Admin-Token') or qs.get('admin_token', [None])[0]
        if not admin_token or not agent_api.verify_admin_token(admin_token):
            self._send_json({'error': 'Invalid admin token'}, 403)
            return
        try:
            from lib import skill_acquire_api
            skill_type = qs.get('type', [None])[0]
            runtime = qs.get('runtime', [None])[0]
            keyword = qs.get('keyword', [None])[0]
            agent_id = qs.get('agent_id', [None])[0]
            visibility = qs.get('visibility', [None])[0]
            results = skill_acquire_api.discover_skills(
                skill_type=skill_type, runtime=runtime, keyword=keyword,
            )
            if agent_id:
                filtered = []
                for r in results:
                    vis = r.get('visibility', 'SHARED')
                    owner = r.get('owned_by_agent', '')
                    if vis != 'PRIVATE' or owner == agent_id:
                        filtered.append(r)
                results = filtered
            if visibility:
                results = [r for r in results if r.get('visibility', 'SHARED') == visibility]
            self._send_json({'skills': [_clean_row(r) for r in results]})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_skill_acquire(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        admin_token = self.headers.get('X-Admin-Token') or qs.get('admin_token', [None])[0]
        if not admin_token or not agent_api.verify_admin_token(admin_token):
            self._send_json({'error': 'Invalid admin token'}, 403)
            return
        path = parsed.path.rstrip('/')
        parts = path.split('/')
        try:
            skill_id_idx = parts.index('skill') + 1
            skill_id = parts[skill_id_idx]
        except (ValueError, IndexError):
            self._send_json({'error': 'Invalid skill ID'}, 400)
            return
        include_resource = qs.get('resource', ['0'])[0] == '1'
        try:
            from lib import skill_acquire_api
            if include_resource:
                result = skill_acquire_api.acquire_skill_full(skill_id)
            else:
                result = skill_acquire_api.acquire_skill_text(skill_id)
            if result is None:
                self._send_json({'error': 'Skill not found or not active'}, 404)
                return
            if include_resource and result.get('resource_zip'):
                import base64
                result['resource_zip'] = base64.b64encode(result['resource_zip']).decode('ascii')
                result['resource_encoding'] = 'base64'
            self._send_json(_clean_row(result))
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _verify_admin_token_from_body(self):
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        token = data.get('admin_token', '')
        if not token or not agent_api.verify_admin_token(token):
            self._send_json({'error': 'Invalid admin token'}, 403)
            return None
        return data

    def _handle_admin_skill_create(self):
        data = self._verify_admin_token_from_body()
        if data is None:
            return
        try:
            from lib import skill_api
            skill_id = skill_api.register_skill(
                title=data.get('title', ''),
                skill_name=data.get('skill_name', ''),
                skill_version=data.get('skill_version', '1.0.0'),
                skill_type=data.get('skill_type', 'CUSTOM'),
                skill_format=data.get('skill_format', 'TEXT'),
                text_content=data.get('text_content'),
                skill_description=data.get('skill_description'),
                runtime=data.get('runtime', 'PYTHON'),
                parameters=data.get('parameters'),
                dependencies=data.get('dependencies'),
                category=data.get('category'),
                owned_by_agent=data.get('owned_by_agent'),
                visibility=data.get('visibility', 'SHARED'),
            )
            skill = skill_api.get_skill(skill_id)
            self._send_json({'skill_id': skill_id, 'skill': _clean_row(skill)})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_skill_update(self):
        data = self._verify_admin_token_from_body()
        if data is None:
            return
        skill_id = data.get('skill_id', '')
        if not skill_id:
            self._send_json({'error': 'skill_id required'}, 400)
            return
        try:
            from lib import skill_api
            update_fields = {k: v for k, v in data.items() if k not in ('admin_token', 'skill_id')}
            ok = skill_api.update_skill(skill_id, **update_fields)
            if ok:
                skill = skill_api.get_skill(skill_id)
                self._send_json({'skill_id': skill_id, 'skill': _clean_row(skill)})
            else:
                self._send_json({'error': 'Skill not found or no changes'}, 404)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_skill_delete(self):
        data = self._verify_admin_token_from_body()
        if data is None:
            return
        skill_id = data.get('skill_id', '')
        if not skill_id:
            self._send_json({'error': 'skill_id required'}, 400)
            return
        try:
            from lib import skill_api
            ok = skill_api.delete_skill(skill_id)
            if ok:
                self._send_json({'skill_id': skill_id, 'deleted': True})
            else:
                self._send_json({'error': 'Skill not found'}, 404)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_admin_skill_upload(self):
        data = self._verify_admin_token_from_body()
        if data is None:
            return
        skill_id = data.get('skill_id', '')
        if not skill_id:
            self._send_json({'error': 'skill_id required'}, 400)
            return
        filename = data.get('filename', '')
        content_b64 = data.get('content_base64', '')
        if not filename or not content_b64:
            self._send_json({'error': 'filename and content_base64 required'}, 400)
            return
        try:
            import base64
            content = base64.b64decode(content_b64)
            from lib import skill_api
            result = skill_api.upload_skill_resource(skill_id, filename, content)
            if result:
                self._send_json({'skill_id': skill_id, 'upload': _clean_row(result)})
            else:
                self._send_json({'error': 'Skill not found'}, 404)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_portal_llm_select(self):
        sess_data = _get_session(self)
        if not sess_data:
            self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
            return
        try:
            data = json.loads(self._read_body() or '{}')
            profile_id = str(data.get('profile_id') or '').strip()
            options = platform_agent_pool.portal_llm_options()
            allowed = {str(item.get('profile_id')) for item in options.get('items') or []}
            if not profile_id or profile_id not in allowed:
                self._send_json({'success': False, 'error': 'LLM profile is not allowed for Portal'}, 403)
                return
            sess_data[1]['llm_profile_id'] = profile_id
            actor = sess_data[1].get('principal_id', sess_data[1].get('user_id', ''))
            connection.execute_transaction_callback(lambda tx: identity_api._audit_tx(tx, actor, 'PORTAL_LLM_SWITCH', 'LLM_PROFILE', profile_id, 'ALLOW', 'Portal user switched to an administrator-allowlisted LLM'))
            self._send_json({'success': True, 'profile_id': profile_id})
        except Exception as exc:
            self._send_json({'success': False, 'error': str(exc)}, 400)

    def _portal_selected_llm(self, sess):
        profile_id = str(sess.get('llm_profile_id') or '')
        options = platform_agent_pool.portal_llm_options()
        allowed = {str(item.get('profile_id')) for item in options.get('items') or []}
        if profile_id not in allowed:
            profile_id = str(options.get('default_profile_id') or '')
        if not profile_id:
            return None
        return {str(k).lower(): v for k, v in dict(connection.execute_query_one(
            "SELECT PROFILE_ID,PROVIDER_URL,MODEL_ID,API_KEY_CIPHER,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {'id': profile_id}) or {}).items()}

    def _handle_portal_chat_send(self):
        try:
            sess_data = _get_session(self)
            if not sess_data:
                self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
                return
            session_id, sess = sess_data
            if self._require_registered_session_agent() is None:
                return
            body = self._read_body()
            data = json.loads(body) if body else {}
            message = data.get('message', '').strip()
            if not message:
                self._send_json({'success': False, 'error': 'Empty message'})
                return
            agent_id = sess.get('agent_id', '')
            user_id = sess.get('user_id', '')
            workspace_id = sess.get('workspace_id', '')
            use_stream = data.get('stream', False)

            ctx_id = None
            if workspace_id:
                _clear_portal_agent_context()
                ctx_data = {'role': 'user', 'content': message, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')}
                ctx_id = workspace_api.save_context(
                    workspace_id=workspace_id,
                    agent_id=agent_id or user_id,
                    context_type='CHAT_MESSAGE',
                    context_data=ctx_data,
                )
                # Auto-name: if workspace name is "New Chat", rename based on first message
                try:
                    ws_info = connection.execute_query_one(
                        "SELECT WORKSPACE_NAME, WORKSPACE_ALIAS FROM WORKSPACES WHERE WORKSPACE_ID = :v_wid",
                        {"v_wid": workspace_id},
                    )
                    if ws_info:
                        current_name = ws_info.get('workspace_alias') or ws_info.get('workspace_name', '')
                        if current_name == 'New Chat' or not current_name:
                            auto_name = message[:40] + ('...' if len(message) > 40 else '')
                            connection.execute(
                                "UPDATE WORKSPACES SET WORKSPACE_ALIAS = :v_name, UPDATED_AT = CURRENT_TIMESTAMP WHERE WORKSPACE_ID = :v_wid",
                                {"v_name": auto_name, "v_wid": workspace_id},
                            )
                except Exception:
                    pass

            selected_profile = self._portal_selected_llm(sess)
            if selected_profile is None:
                self._send_json({'success': False, 'error': 'Portal LLM policy has no usable default profile'}, 503)
                return
            if use_stream:
                self._handle_chat_stream(message, agent_id, user_id, workspace_id, sess, ctx_id, selected_profile)
            else:
                _set_portal_agent_context(sess)
                try:
                    reply = native_runtime._call_llm(selected_profile, [{"role": "user", "content": message}])["content"]
                except Exception:
                    reply = None
                if not reply:
                    reply = _generate_sim_reply(message, agent_id, sess)
                if workspace_id:
                    reply_data = {'role': 'agent', 'content': reply, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')}
                    workspace_api.save_context(
                        workspace_id=workspace_id,
                        agent_id=agent_id or user_id,
                        context_type='CHAT_MESSAGE',
                        context_data=reply_data,
                    )
                self._send_json({
                    'success': True,
                    'reply': reply,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'user_context_id': ctx_id,
                })
        except Exception as e:
            self._send_json({'success': False, 'error': str(e)}, 500)

    def _handle_chat_stream(self, message, agent_id, user_id, workspace_id, sess, ctx_id, selected_profile=None):
        """Send chat reply as SSE stream with token-by-token output."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        def send_sse(data):
            self.wfile.write(f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        full_reply = ""
        model = _select_model_for_task("standard")
        stream = None
        if selected_profile:
            try:
                events = queue.Queue()
                sentinel = object()
                def run_selected_profile():
                    try:
                        result = native_runtime._stream_llm(
                            selected_profile, [{"role": "user", "content": message}],
                            lambda delta: events.put(("delta", delta)),
                        )
                        events.put(("done", result))
                    except Exception as exc:
                        events.put(("error", exc))
                    finally:
                        events.put(("stop", sentinel))
                threading.Thread(target=run_selected_profile, daemon=True).start()
                def selected_events():
                    while True:
                        kind, value = events.get()
                        if kind == "delta":
                            yield str(value)
                        elif kind == "error":
                            raise value
                        elif kind == "stop":
                            return
                stream = selected_events()
            except Exception:
                stream = None
        if stream is None:
            stream = _call_llm_stream([{"role": "user", "content": message}], model=model)

        if stream is not None:
            for token in stream:
                full_reply += token
                send_sse({"type": "token", "content": token})
        else:
            full_reply = _generate_sim_reply(message, agent_id, sess)
            send_sse({"type": "token", "content": full_reply})

        if workspace_id:
            reply_data = {'role': 'agent', 'content': full_reply, 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')}
            workspace_api.save_context(
                workspace_id=workspace_id,
                agent_id=agent_id or user_id,
                context_type='CHAT_MESSAGE',
                context_data=reply_data,
            )

        send_sse({"type": "done", "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S')})
        _set_portal_agent_context(sess)

    def _handle_portal_chat_new(self):
        session_data = _get_session(self)
        if not session_data:
            self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
            return
        sess = session_data[1]
        agent_id = sess.get('agent_id', '')
        user_id = sess.get('user_id', '')
        if not agent_id:
            self._send_json({'success': False, 'error': 'No agent assigned'}, 400)
            return
        if self._require_registered_session_agent() is None:
            return
        try:
            body = self._read_body()
            data = json.loads(body) if body else {}
            fork_context_id = data.get('fork_context_id', '')
            agent_session_id = sess.get('agent_session_id', '')
            connection.set_agent_context(None)
            if agent_session_id:
                agent_api.end_session(agent_session_id)
            new_session = agent_api.create_session(agent_id, owner_user_id=user_id)
            sess['agent_session_id'] = new_session
            ws = workspace_api.create_workspace(owner_user_id=user_id, name='New Chat', workspace_type='CONVERSATION')
            sess['workspace_id'] = ws
            if fork_context_id:
                branch = branch_api.fork_branch(
                    workspace_id=ws,
                    fork_context_id=fork_context_id,
                    branch_type='EXPLORATION',
                    agent_id=agent_id,
                )
                sess['branch_id'] = branch.get('branch_id', '')
            _set_portal_agent_context(sess)
            self._send_json({'success': True})
        except Exception as e:
            self._send_json({'success': False, 'error': str(e)}, 500)

    def _handle_portal_chat_rename(self):
        session_data = _get_session(self)
        if not session_data:
            self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
            return
        try:
            body = self._read_body()
            data = json.loads(body)
            ws_id = str(data.get('workspace_id') or '').strip()
            new_name = data.get('name', '').strip()
            if not ws_id or not new_name:
                self._send_json({'success': False, 'error': 'workspace_id and name required'}, 400)
                return
            connection.set_agent_context(None)
            connection.execute(
                "UPDATE WORKSPACES SET WORKSPACE_ALIAS = :v_name, UPDATED_AT = CURRENT_TIMESTAMP WHERE WORKSPACE_ID = :v_wid",
                {"v_name": new_name, "v_wid": ws_id},
            )
            if session_data[1].get('agent_id'):
                connection.set_agent_context(session_data[1]['agent_id'])
            self._send_json({'success': True})
        except Exception as e:
            self._send_json({'success': False, 'error': str(e)}, 500)

    def _handle_portal_agent_release(self):
        session_data = _get_session(self)
        if not session_data:
            self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
            return
        release_error = ''
        try:
            connection.set_agent_context(None)
            _clear_portal_agent_context()
            sess = session_data[1]
            agent_session_id = sess.get('agent_session_id')
            if agent_session_id:
                agent_api.end_session(agent_session_id)
            agent_id = sess.get('agent_id')
            if agent_id and not agent_api.hibernate_agent(agent_id, _portal_node_id()):
                release_error = 'Agent could not be released'
            sess.pop('agent_id', None)
            sess.pop('agent_session_id', None)
        except Exception as exc:
            release_error = str(exc)
            logger.warning('Portal Agent release failed; completing browser sign-out', exc_info=True)
        finally:
            # Portal Exit is a security boundary, not merely an Agent-pool
            # release. Revoke this Portal session and any Dashboard session
            # presented by the same browser so switching to /app requires a
            # fresh Dashboard admission.
            raw_portal_session_id = session_data[0]
            dashboard_cookie = SimpleCookie(self.headers.get('Cookie', ''))
            dashboard_name = _get_cookie_name('DASHBOARD')
            raw_dashboard_session_id = (
                dashboard_cookie[dashboard_name].value
                if dashboard_name in dashboard_cookie else ''
            )
            for raw_session_id, reason in (
                (raw_portal_session_id, 'portal exit'),
                (raw_dashboard_session_id, 'portal exit browser sign-out'),
            ):
                if raw_session_id:
                    try:
                        identity_api.revoke_session(raw_session_id, reason)
                    except Exception:
                        logger.warning('Unable to revoke browser session during Portal Exit', exc_info=True)
            sessions.pop(raw_portal_session_id, None)
        body = json.dumps({
            'success': True,
            'message': 'Agent released' if not release_error else 'Browser session ended; Agent release will be reconciled',
            'agent_release_pending': bool(release_error),
        }).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for scope in ('PORTAL', 'DASHBOARD'):
            self.send_header('Set-Cookie', '{}=; Path=/; Max-Age=0; SameSite=Lax'.format(_get_cookie_name(scope)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_portal_chat_delete(self):
        session_data = _get_session(self)
        if not session_data:
            self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
            return
        sess = session_data[1]
        user_id = sess.get('user_id', '')
        try:
            body = self._read_body()
            data = json.loads(body)
            ws_id = str(data.get('workspace_id') or '').strip()
            if not ws_id:
                self._send_json({'success': False, 'error': 'workspace_id required'}, 400)
                return
            connection.set_agent_context(None)
            ws = connection.execute_query_one(
                "SELECT WORKSPACE_ID FROM WORKSPACES WHERE WORKSPACE_ID = :v_wid AND OWNER_USER_ID = :v_uid",
                {"v_wid": ws_id, "v_uid": user_id},
            )
            if not ws:
                if sess.get('agent_id'):
                    connection.set_agent_context(sess['agent_id'])
                self._send_json({'success': False, 'error': 'Workspace not found'}, 404)
                return
            connection.execute("DELETE FROM WORKSPACE_CONTEXT WHERE WORKSPACE_ID = :v_wid", {"v_wid": ws_id})
            connection.execute("DELETE FROM WORKSPACES WHERE WORKSPACE_ID = :v_wid", {"v_wid": ws_id})
            if sess.get('agent_id'):
                connection.set_agent_context(sess['agent_id'])
            if sess.get('workspace_id') == ws_id:
                sess.pop('workspace_id', None)
            self._send_json({'success': True})
        except Exception as e:
            self._send_json({'success': False, 'error': str(e)}, 500)

    def _handle_portal_chat_switch(self):
        session_data = _get_session(self)
        if not session_data:
            self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
            return
        sess = session_data[1]
        user_id = sess.get('user_id', '')
        try:
            body = self._read_body()
            data = json.loads(body)
            ws_id = str(data.get('workspace_id') or '').strip()
            if not ws_id:
                self._send_json({'success': False, 'error': 'workspace_id required'}, 400)
                return
            connection.set_agent_context(None)
            ws = connection.execute_query_one(
                "SELECT WORKSPACE_ID FROM WORKSPACES WHERE WORKSPACE_ID = :v_wid AND OWNER_USER_ID = :v_uid AND STATUS = 'ACTIVE'",
                {"v_wid": ws_id, "v_uid": user_id},
            )
            if not ws:
                if sess.get('agent_id'):
                    connection.set_agent_context(sess['agent_id'])
                self._send_json({'success': False, 'error': 'Workspace not found'}, 404)
                return
            if sess.get('agent_id'):
                connection.set_agent_context(sess['agent_id'])
            sess['workspace_id'] = ws_id
            self._send_json({'success': True})
        except Exception as e:
            self._send_json({'success': False, 'error': str(e)}, 500)

    def _handle_portal_api_get(self, path, qs):
        if path not in PUBLIC_API:
            session_data = _get_session(self)
            if not session_data:
                self._send_json({'success': False, 'error': 'Not authenticated'}, 401)
                return
            sess = session_data[1]
        try:
            if path == '/portal/api/user/profile':
                session_data = _get_session(self)
                if session_data:
                    connection.set_agent_context(None)
                    profile = user_api.get_user_profile(session_data[1].get('user_id', ''))
                    if session_data[1].get('agent_id'):
                        connection.set_agent_context(session_data[1]['agent_id'])
                    self._send_json(_clean_row(profile) if profile else {'error': 'User not found'})
                else:
                    self._send_json({'error': 'Not authenticated'}, 401)
            elif path == '/portal/api/llm-profiles':
                self._send_json(platform_agent_pool.portal_llm_options())
            elif path == '/portal/api/agent/status':
                session_data = _get_session(self)
                if session_data:
                    agent_id = session_data[1].get('agent_id', '')
                    if agent_id:
                        agent = agent_api.get_agent(agent_id)
                        self._send_json(_clean_row(agent) if agent else {'error': 'Agent not found'})
                    else:
                        self._send_json({'has_agent': False})
                else:
                    self._send_json({'error': 'Not authenticated'}, 401)
            elif path == '/portal/api/chat/history':
                session_data = _get_session(self)
                if session_data:
                    user_id = session_data[1].get('user_id', '')
                    workspace_id = session_data[1].get('workspace_id', '')
                    if workspace_id:
                        connection.set_agent_context(None)
                        rows = connection.execute_query("""
                            SELECT CONTEXT_ID, CONTEXT_DATA FROM WORKSPACE_CONTEXT
                            WHERE CONTEXT_TYPE = 'CHAT_MESSAGE' AND WORKSPACE_ID = :v_wid
                            ORDER BY CREATED_AT ASC
                        """, {"v_wid": workspace_id})
                        messages = []
                        for r in rows:
                            try:
                                cd = r.get('context_data', '{}')
                                d = cd if isinstance(cd, dict) else json.loads(cd)
                                d['context_id'] = r.get('context_id', '')
                                messages.append(d)
                            except Exception:
                                pass
                        if session_data[1].get('agent_id'):
                            connection.set_agent_context(session_data[1]['agent_id'])
                        self._send_json({'messages': messages, 'workspace_id': workspace_id})
                    else:
                        self._send_json({'messages': []})
                else:
                    self._send_json({'error': 'Not authenticated'}, 401)
            elif path == '/portal/api/chat/sessions':
                session_data = _get_session(self)
                if session_data:
                    user_id = session_data[1].get('user_id', '')
                    current_ws = session_data[1].get('workspace_id', '')
                    connection.set_agent_context(None)
                    rows = connection.execute_query("""
                        SELECT w.WORKSPACE_ID, w.WORKSPACE_NAME, w.WORKSPACE_ALIAS,
                               TO_CHAR(w.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                               (SELECT COUNT(*) FROM WORKSPACE_CONTEXT wc WHERE wc.WORKSPACE_ID = w.WORKSPACE_ID AND wc.CONTEXT_TYPE = 'CHAT_MESSAGE') AS MSG_COUNT
                        FROM WORKSPACES w
                        WHERE w.OWNER_USER_ID = :v_uid AND w.WORKSPACE_TYPE = 'CONVERSATION' AND w.STATUS = 'ACTIVE'
                        ORDER BY w.CREATED_AT DESC
                    """, {"v_uid": user_id})
                    sessions_list = []
                    for r in rows:
                        sessions_list.append({
                            'workspace_id': str(r['workspace_id']),
                            'name': r.get('workspace_alias') or r.get('workspace_name', ''),
                            'created_at': r.get('created_at', ''),
                            'msg_count': r.get('msg_count', 0),
                            'is_current': str(r['workspace_id']) == str(current_ws),
                        })
                    if session_data[1].get('agent_id'):
                        connection.set_agent_context(session_data[1]['agent_id'])
                    self._send_json({'sessions': sessions_list})
                else:
                    self._send_json({'error': 'Not authenticated'}, 401)
            elif path == '/portal/api/user/workspaces':
                session_data = _get_session(self)
                if session_data:
                    connection.set_agent_context(None)
                    wss = user_api.get_user_workspaces(session_data[1].get('user_id', ''))
                    if session_data[1].get('agent_id'):
                        connection.set_agent_context(session_data[1]['agent_id'])
                    self._send_json({'workspaces': [_clean_row(w) for w in wss]})
                else:
                    self._send_json({'error': 'Not authenticated'}, 401)
            elif path == '/portal/api/user/memories':
                session_data = _get_session(self)
                if session_data:
                    connection.set_agent_context(None)
                    mems = user_api.get_user_memories(session_data[1].get('user_id', ''))
                    if session_data[1].get('agent_id'):
                        connection.set_agent_context(session_data[1]['agent_id'])
                    self._send_json({'memories': [_clean_row(m) for m in mems]})
                else:
                    self._send_json({'error': 'Not authenticated'}, 401)
            else:
                self._send_error(404, 'Not found')
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    # -- Loop Engineering API handlers --

    def _api_loops_list(self, qs):
        status = qs.get('status', [None])[0]
        agent_id = qs.get('agent_id', [None])[0]
        loops = loop_api.list_loops(status=status, agent_id=agent_id)
        for l in loops:
            l['stats'] = loop_api.get_loop_stats(l['loop_id'])
        self._send_json({'loops': loops})

    def _api_loops_get(self, path):
        loop_id = path.split('/')[-1]
        loop = loop_api.get_loop(loop_id)
        if not loop:
            self._send_error(404, 'Loop not found'); return
        loop['stats'] = loop_api.get_loop_stats(loop_id)
        loop['hooks'] = loop_api.list_hooks(loop_id)
        self._send_json(loop)

    def _api_loops_runs(self, path, qs):
        loop_id = path.split('/')[-2]
        status = qs.get('status', [None])[0]
        runs = loop_api.list_runs(loop_id=loop_id, status=status)
        self._send_json({'runs': runs})

    def _api_loops_iterations(self, path, qs):
        run_id = path.split('/')[-2]
        limit = int(qs.get('limit', ['50'])[0])
        iters = loop_api.list_iterations(run_id, limit=limit)
        self._send_json({'iterations': iters})

    def _api_loops_stats(self, path):
        loop_id = path.split('/')[-2]
        self._send_json(loop_api.get_loop_stats(loop_id))

    def _api_loops_hooks(self, path):
        loop_id = path.split('/')[-2]
        self._send_json({'hooks': loop_api.list_hooks(loop_id)})

    def _api_run_get(self, path):
        run_id = path.split('/')[-1]
        run = loop_api.get_run(run_id)
        if not run:
            self._send_error(404, 'Run not found'); return
        self._send_json(run)

    def _handle_loop_create(self):
        data = json.loads(self._read_body())
        loop_id = data.get('loop_id')
        if loop_id:
            ok = loop_api.update_loop(loop_id, **{k: v for k, v in data.items() if k != 'loop_id'})
            self._send_json({'success': ok, 'loop_id': loop_id})
            return
        loop_id = loop_api.create_loop(
            title=data['title'],
            goal_definition=data.get('goal_definition') or {"goal": data['title']},
            stop_conditions=data.get('stop_conditions') or {"max_iterations": 10},
            evaluation_config=data.get('evaluation_config') or {"eval_type": "MANUAL"},
            summary=data.get('summary'),
            trigger_config=data.get('trigger_config'),
            harness_template_id=data.get('harness_template_id'),
            workspace_id=data.get('workspace_id'),
            branch_id=data.get('branch_id'),
            owned_by_agent=data.get('agent_id') or data.get('owned_by_agent'),
            visibility=data.get('visibility', 'PRIVATE'),
        )
        self._send_json({'success': True, 'loop_id': loop_id})

    def _handle_loop_delete(self):
        data = json.loads(self._read_body())
        loop_api.delete_loop(data['loop_id'])
        self._send_json({'success': True})

    def _handle_loop_run_start(self):
        data = json.loads(self._read_body())
        run_id = loop_api.start_run(data['loop_id'],
                                    data.get('agent_id', 'system'),
                                    data.get('trigger_type', 'MANUAL'),
                                    data.get('trigger_source'))
        self._send_json({'success': True, 'run_id': run_id})

    def _handle_loop_run_control(self, action):
        data = json.loads(self._read_body())
        run_id = data['run_id']
        if action == 'pause':
            loop_api.pause_run(run_id)
        elif action == 'resume':
            loop_api.resume_run(run_id)
        elif action == 'stop':
            loop_api.stop_run(run_id, data.get('reason'))
        self._send_json({'success': True})

    def _handle_loop_iterate(self):
        data = json.loads(self._read_body())
        result = loop_api.execute_loop_iteration(
            run_id=data['run_id'], agent_id=data.get('agent_id', ''),
            plan_data=data.get('plan_data'),
            actions=data.get('actions'),
            observations=data.get('observations'),
            token_usage=data.get('token_usage', 0),
        )
        self._send_json({'success': True, 'result': result})

    def _handle_loop_hook_add(self):
        data = json.loads(self._read_body())
        hook_id = loop_api.add_hook(data['loop_id'], data['hook_event'],
                                    data['hook_type'], data.get('hook_config'),
                                    data.get('priority', 5))
        self._send_json({'success': True, 'hook_id': hook_id})

    def _api_loops_from_spec(self):
        from lib.loop_api import create_loop_from_spec
        data = json.loads(self._read_body())
        loop_id = create_loop_from_spec(data['spec_id'], data['agent_id'], **{k:v for k,v in data.items() if k not in ('spec_id','agent_id')})
        self._send_json({'success': True, 'loop_id': loop_id})

    def _api_loops_collab(self):
        from lib.loop_api import create_collab_loop
        data = json.loads(self._read_body())
        loop_id = create_collab_loop(data['group_id'], data.get('parent_loop_id'), data['agent_id'], **{k:v for k,v in data.items() if k not in ('group_id','parent_loop_id','agent_id')})
        self._send_json({'success': True, 'loop_id': loop_id})

    def _api_loops_children(self, path):
        from lib.loop_api import list_loops
        loop_id = path.split('/')[-2]
        children = list_loops(parent_loop_id=loop_id)
        self._send_json({'children': children})

    def _api_loops_aggregation(self, path):
        from lib.loop_api import aggregate_child_runs, list_runs
        loop_id = path.split('/')[-2]
        runs = list_runs(loop_id=loop_id, limit=1)
        if runs:
            parent_run_id = runs[0].get('run_id')
            agg = aggregate_child_runs(parent_run_id)
            self._send_json(agg)
        else:
            self._send_json({'total': 0, 'completed': 0, 'failed': 0, 'running': 0, 'results': []})

    def _api_task_step_bind_loop(self, path):
        from lib.task_plan_api import bind_loop_to_step
        step_id = path.split('/')[4]
        data = json.loads(self._read_body())
        binding_id = bind_loop_to_step(step_id, data['loop_id'], data.get('binding_type', 'COMPLETION'), data.get('auto_start', 'N'))
        self._send_json({'success': True, 'binding_id': binding_id})

    def _api_task_step_loop(self, path):
        from lib.task_plan_api import get_step_loop
        step_id = path.split('/')[4]
        binding = get_step_loop(step_id)
        self._send_json(binding or {})

    def _api_collab_loop(self, path):
        from lib.collab_api import create_group_loop
        group_id = path.split('/')[3]
        data = json.loads(self._read_body())
        loop_id = create_group_loop(group_id, data['title'], data['goal_definition'], data['agent_id'], **{k:v for k,v in data.items() if k not in ('title','goal_definition','agent_id')})
        self._send_json({'success': True, 'loop_id': loop_id})

    def _api_audit_list(self, qs):
        from lib import audit_api
        limit = int(qs.get('limit', ['100'])[0])
        events = audit_api.get_audit_events(limit=limit)
        try:
            stats = audit_api.get_audit_stats()
        except Exception:
            stats = {}
        self._send_json({"events": events, "stats": stats})

    def _api_audit_stats(self, qs):
        from lib import audit_api
        stats = audit_api.get_audit_stats()
        self._send_json(stats)

    def _api_approvals_list(self, qs):
        from lib import approval_api
        entity_type = qs.get('type', [None])[0]
        if entity_type:
            items = [a for a in approval_api.list_all(limit=50) if a.get("entity_type") == entity_type]
        else:
            items = approval_api.list_all(limit=50)
        self._send_json({"approvals": items})

    def _api_approvals_stats(self, qs):
        from lib import approval_api
        stats = approval_api.get_stats()
        self._send_json(stats)

    def _api_approval_approve(self, path):
        from lib import approval_api
        approval_id = path.split('/')[-2]
        self._read_body()  # Client attribution is intentionally ignored.
        actor = self._authenticated_actor()
        result = approval_api.approve(approval_id, actor)
        self._send_json({"success": result})

    def _api_approval_reject(self, path):
        from lib import approval_api
        approval_id = path.split('/')[-2]
        body = self._read_body()
        data = json.loads(body) if body else {}
        actor = self._authenticated_actor()
        reason = data.get('reason', '')
        result = approval_api.reject(approval_id, actor, reason)
        self._send_json({"success": result})

    # ==================== v3.9.0 Agent Protocol ====================

    def _api_ap_create_task(self):
        """Agent Protocol: POST /ap/v1/agent/tasks — create a task."""
        from lib import task_plan_api
        body = self._read_body()
        data = json.loads(body) if body else {}
        goal = data.get('input', data.get('goal', ''))
        agent_id = data.get('agent_id', 'system')
        plan_id = task_plan_api.create_plan(agent_id=agent_id, goal=goal)
        self._send_json({"task_id": plan_id, "input": goal, "status": "CREATED"})

    def _api_ap_execute_step(self, path):
        """Agent Protocol: POST /ap/v1/agent/tasks/{task_id}/steps — execute a step."""
        from lib import task_plan_api
        parts = path.split('/')
        task_id = parts[-2]
        body = self._read_body()
        data = json.loads(body) if body else {}
        steps = task_plan_api.list_steps(task_id)
        if not steps:
            self._send_json({"error": "No steps found for task"}, 404)
            return
        step_id = data.get('step_id', steps[0].get('step_id', ''))
        if edition_features.has_feature('orchestrator'):
            result = orchestrator.execute_step_with_retry(step_id)
        else:
            updated = task_plan_api.update_step(step_id, status='SUCCESS')
            result = bool(updated)
        self._send_json({
            "task_id": task_id,
            "step_id": step_id,
            "is_last": result,
            "output": "executed" if result else "pending",
        })

    def _serve_template(self, filename):
        filepath = os.path.join(TEMPLATES_DIR, filename)
        if not os.path.isfile(filepath):
            self._send_error(404, 'Template not found')
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                html = f.read()
            timeout = _session_timeout()
            html = html.replace('4.4.4', VERSION)
            html = html.replace('2026-08-14', os.environ.get('AI_AGENT_RELEASE_DATE', ''))
            html = html.replace('{{DB_DISPLAY}}', _product_database_display())
            html = html.replace('{{EDITION_TIER}}', _product_tier())
            html = html.replace(
                '{{EDITION_LABEL}}',
                '{} {} Edition'.format(_product_database_display(), _product_tier()),
            )
            html = html.replace('{{SESSION_TIMEOUT}}', str(timeout))
            html = html.replace(
                '{{SESSION_TIMEOUT_DISPLAY}}',
                '{:02d}:{:02d}'.format(timeout // 60, timeout % 60),
            )
            self._send_html(html)
        except Exception as e:
            self._send_error(500, str(e))

    def _serve_static(self, filepath):
        try:
            base = os.path.realpath(STATIC_DIR)
            requested = os.path.realpath(os.path.join(base, urllib.parse.unquote(filepath)))
        except (TypeError, ValueError):
            self._send_error(400, 'Invalid static path')
            return
        if requested != base and not requested.startswith(base + os.sep):
            self._send_error(403, 'Invalid static path')
            return
        full = requested
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
            self.send_header('Cache-Control', 'no-store, max-age=0')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_error(500, str(e))


    def _api_messages_list(self, qs):
        group_id = qs.get('group_id', [None])[0]
        agent_id = qs.get('agent_id', [None])[0]
        messages = message_api.get_messages(group_id=group_id, agent_id=agent_id)
        self._send_json(messages)

    def _api_messages_inbox(self, qs):
        group_id = qs.get('group_id', [None])[0]
        agent_id = qs.get('agent_id', [None])[0]
        if not group_id or not agent_id:
            self._send_json({'error': 'group_id and agent_id required'}, 400)
            return
        self._send_json(message_api.get_group_inbox(group_id, agent_id))

    def _api_messages_unread(self, qs):
        agent_id = qs.get('agent_id', [None])[0]
        group_id = qs.get('group_id', [None])[0]
        if not agent_id:
            self._send_json({'error': 'agent_id required'}, 400)
            return
        count = message_api.get_unread_count(agent_id, group_id)
        self._send_json({'unread_count': count})

    def _api_messages_thread(self, path):
        message_id = path.split('/')[-2]
        self._send_json(message_api.get_conversation(message_id))

    def _api_messages_send(self):
        body = self._read_body()
        data = json.loads(body)
        msg_id = message_api.send_message(
            group_id=data['group_id'], sender_agent_id=data['sender_agent_id'],
            body=data['body'], receiver_agent_id=data.get('receiver_agent_id'),
            subject=data.get('subject'), message_type=data.get('message_type', 'TEXT'),
            priority=data.get('priority', 'NORMAL'),
            parent_message_id=data.get('parent_message_id'),
            attachment_entity_id=data.get('attachment_entity_id'),
        )
        self._send_json({'message_id': msg_id}, 201)

    def _api_messages_read(self, path):
        message_id = path.split('/')[-2]
        body = self._read_body()
        data = json.loads(body)
        ok = message_api.mark_read(message_id, data['agent_id'])
        self._send_json({'success': ok})

    def _api_messages_delete(self, path):
        message_id = path.split('/')[-2]
        body = self._read_body()
        data = json.loads(body)
        ok = message_api.delete_message(message_id, data['agent_id'])
        self._send_json({'success': ok})

    def _api_orch_status(self, qs):
        plan_id = qs.get('plan_id', [None])[0]
        if not plan_id:
            self._send_json({'error': 'plan_id required'}, 400)
            return
        self._send_json(orchestrator.get_execution_status(plan_id))

    def _api_orch_dag_resolve(self, path):
        plan_id = path.split('/')[-1]
        self._send_json(orchestrator.resolve_dag(plan_id))

    def _api_orch_dag_execute(self, path):
        plan_id = path.split('/')[-1]
        self._send_json(orchestrator.execute_dag(plan_id))

    def _api_orch_retry_policy(self):
        body = self._read_body()
        data = json.loads(body)
        step_id = path.split('/')[-2]
        policy_id = orchestrator.add_retry_policy(step_id, **data)
        self._send_json({'policy_id': policy_id}, 201)

    def _api_orch_fan_out(self, path):
        loop_id = path.split('/')[-2]
        body = self._read_body()
        data = json.loads(body)
        result = orchestrator.fan_out(
            step_id=data['step_id'], agent_ids=data['agent_ids'],
            loop_goal=data['loop_goal'], evaluation_type=data.get('evaluation_type', 'AGGREGATE'),
        )
        self._send_json(result, 201)

    def _api_orch_fan_in(self, path):
        parent_loop_id = path.split('/')[-2]
        body = self._read_body()
        data = json.loads(body)
        result = orchestrator.fan_in(parent_loop_id, data.get('strategy', 'CONSENSUS'))
        self._send_json(result)

    def _api_monitor_overview(self):
        self._send_json(monitor_api.get_system_overview())

    def _api_monitor_agents(self):
        self._send_json(monitor_api.get_agent_health())

    def _api_monitor_stalls(self, qs):
        threshold = int(qs.get('threshold_minutes', ['10'])[0])
        self._send_json(monitor_api.get_stalled_agents(threshold))

    def _api_monitor_metrics(self, qs):
        since = qs.get('since', [None])[0]
        self._send_json(monitor_api.get_performance_metrics(since))

    def _api_monitor_alerts(self):
        self._send_json(monitor_api.get_active_alerts())

    def _api_traces_list(self, qs):
        agent_id = qs.get('agent_id', [None])[0]
        since = qs.get('since', [None])[0]
        limit = int(qs.get('limit', ['50'])[0])
        self._send_json(trace_api.get_trace_summary(agent_id, since, limit))

    def _api_traces_get(self, path):
        trace_id = path.split('/')[-1]
        self._send_json(trace_api.get_trace_tree(trace_id))

    def _api_traces_tree(self, path):
        trace_id = path.split('/')[-2]
        self._send_json(trace_api.get_trace_tree(trace_id))

    def _api_traces_spans(self, path, qs):
        trace_id = path.split('/')[-2]
        span_type = qs.get('type', ['SESSION'])[0]
        self._send_json(trace_api.get_trace_span(trace_id, span_type))

    def _api_tools_list(self, qs):
        namespace = qs.get('namespace', [None])[0]
        tool_type = qs.get('type', [None])[0]
        self._send_json(tool_registry.list_tools(namespace, tool_type))

    def _api_tools_get(self, path):
        tool_id = path.split('/')[-1]
        tool = tool_registry.get_tool(tool_id)
        if tool:
            self._send_json(tool)
        else:
            self._send_error(404, 'Tool not found')

    def _api_tools_import_openapi(self):
        body = self._read_body()
        data = json.loads(body)
        spec = data.get('spec')
        namespace = data.get('namespace', 'default')
        if not spec:
            self._send_json({'error': 'spec required'}, 400)
            return
        ids = tool_registry.import_openapi(spec, namespace)
        self._send_json({'imported': ids, 'count': len(ids)}, 201)

    def _api_tools_import_url(self):
        body = self._read_body()
        data = json.loads(body)
        url = data.get('url')
        namespace = data.get('namespace', 'default')
        auth_header = data.get('auth_header')
        if not url:
            self._send_json({'error': 'url required'}, 400)
            return
        ids = tool_registry.import_from_url(url, namespace, auth_header)
        self._send_json({'imported': ids, 'count': len(ids)}, 201)

    def _api_tool_chains_list(self):
        self._send_json(tool_registry.list_tool_chains())

    def _api_tool_chain_create(self):
        body = self._read_body()
        data = json.loads(body)
        chain_id = tool_registry.create_tool_chain(
            name=data['name'], steps=data['steps'], description=data.get('description'),
        )
        self._send_json({'chain_id': chain_id}, 201)

    def _api_events_pending(self, qs):
        agent_id = qs.get('agent_id', [None])[0]
        if not agent_id:
            self._send_json({'error': 'agent_id required'}, 400)
            return
        self._send_json(event_bus.get_pending_events(agent_id))

    def _api_events_publish(self):
        body = self._read_body()
        data = json.loads(body)
        event_id = event_bus.publish_event(
            event_type=data['event_type'], source_id=data.get('source_id'),
            source_type=data.get('source_type'), payload=data.get('payload'),
        )
        self._send_json({'event_id': event_id}, 201)

    def _api_events_subscribe(self):
        body = self._read_body()
        data = json.loads(body)
        sub_id = event_bus.subscribe_agent(
            agent_id=data['agent_id'], event_type=data['event_type'],
            filter_pattern=data.get('filter_pattern'),
        )
        self._send_json({'sub_id': sub_id}, 201)

    def _api_events_subscriptions(self, qs):
        agent_id = qs.get('agent_id', [None])[0]
        self._send_json(event_bus.get_subscriptions(agent_id))

    def _api_agents_discover(self, qs):
        capability = qs.get('capability', [None])[0]
        if capability:
            self._send_json(event_bus.discover_agents_by_capability(capability))
        else:
            skill_id = qs.get('skill_id', [None])[0]
            if skill_id:
                self._send_json(event_bus.match_skill_to_agents(skill_id))
            else:
                task = qs.get('task', [None])[0]
                if task:
                    self._send_json(event_bus.recommend_agents(task))
                else:
                    self._send_json({'error': 'capability, skill_id, or task required'}, 400)

    def _api_orch_pipeline(self):
        body = self._read_body()
        data = json.loads(body)
        plan_id = orchestrator.create_pipeline(
            step_ids=data['step_ids'], mode=data.get('mode', 'SEQUENTIAL'),
        )
        self._send_json({'plan_id': plan_id}, 201)

SIM_REPLIES = {
    'hello': 'Hello! I am your AI Agent. How can I help you today?',
    '你好': '你好！我是你的 AI Agent，有什么可以帮你的吗？',
    'help': 'I can help you manage memories, search knowledge, organize tasks, and collaborate with other agents. What would you like to do?',
    'memory': 'I can store and retrieve your memories. Just tell me what you want to remember or recall.',
    'status': 'I am currently active and ready to assist you. All systems are operational.',
    'skill': 'I have access to various skills including knowledge search, memory management, task planning, and workspace organization.',
    'workspace': 'Your workspace is ready. I can help you organize your context and collaborate with team members.',
}


def _call_llm_stream(messages, model=None):
    """Call LLM API in streaming mode, yield tokens one by one.

    Uses config.llm settings. Falls back to None if LLM not configured.
    Yields: token strings, or None on error.
    """
    try:
        from lib.config import get_config
        cfg = get_config()
        llm = cfg.llm
        if not llm.api_url or not llm.model:
            return None

        api_url = llm.api_url.rstrip('/')
        if not api_url.endswith('/chat/completions'):
            api_url += '/chat/completions'

        data = json.dumps({
            "model": model or llm.model,
            "messages": messages,
            "stream": True,
            "max_tokens": 8192,
            "reasoning_effort": "none",
        }).encode()

        headers = {"Content-Type": "application/json"}
        if llm.api_key:
            headers["Authorization"] = f"Bearer {llm.api_key}"

        req = urllib.request.Request(
            api_url,
            data=data,
            headers=headers,
            method="POST",
        )

        resp = urllib.request.urlopen(req, timeout=120)
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.strip()
                if not line or not line.startswith(b"data:"):
                    continue
                data_str = line[5:].lstrip().decode("utf-8", errors="replace")
                if data_str.strip() == "[DONE]":
                    return
                try:
                    chunk_data = json.loads(data_str)
                    delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content") or ""
                    if token:
                        yield token
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

    except Exception as e:
        logger.error("LLM stream error: %s", e)
        return None


def _call_llm(messages, model=None):
    """Call LLM API in non-streaming mode. Returns full response text or None."""
    try:
        from lib.config import get_config
        cfg = get_config()
        llm = cfg.llm
        if not llm.api_url or not llm.model:
            return None

        api_url = llm.api_url.rstrip('/')
        if not api_url.endswith('/chat/completions'):
            api_url += '/chat/completions'

        data = json.dumps({
            "model": model or llm.model,
            "messages": messages,
            "stream": False,
            "max_tokens": 8192,
            "reasoning_effort": "none",
        }).encode()

        headers = {"Content-Type": "application/json"}
        if llm.api_key:
            headers["Authorization"] = f"Bearer {llm.api_key}"

        req = urllib.request.Request(
            api_url,
            data=data,
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            msg = result.get("choices", [{}])[0].get("message", {})
            content = msg.get("content") or ""
            if not content:
                content = msg.get("reasoning_content") or ""
            return content if content else None

    except Exception as e:
        logger.error("LLM call error: %s", e)
        return None


def _select_model_for_task(complexity="standard"):
    """Select model based on task complexity and routing config."""
    from lib.config import get_config
    cfg = get_config()
    mr = cfg.model_routing
    if complexity == "simple" and mr.simple_model:
        return mr.simple_model
    elif complexity == "complex" and mr.complex_model:
        return mr.complex_model
    elif mr.standard_model:
        return mr.standard_model
    return cfg.llm.model if cfg.llm.model else None


def _generate_sim_reply(message, agent_id, sess):
    msg_lower = message.lower().strip()
    for key, reply in SIM_REPLIES.items():
        if key in msg_lower:
            return reply
    agent_name = sess.get('agent_name', 'Agent')
    return f"[{agent_name}] I received your message: \"{message}\". I'm processing it and will respond more intelligently once connected to a real LLM backend. For now, I can help with basic memory, knowledge, and workspace operations."





def main():
    from lib.connection_crypto import auto_encrypt_config
    from pathlib import Path
    config_path = Path(__file__).resolve().parent.parent.parent / "config.json"
    if config_path.exists():
        auto_encrypt_config(config_path)

    cfg = _load_server_config()
    host = getattr(cfg, 'host', '0.0.0.0')
    port = getattr(cfg, 'port', 8000)

    database_ready = False
    try:
        connection.get_pool()
        database_ready = True
        print("[server] Database connection pool initialized")
    except Exception as e:
        print("[server] WARNING: Database connection failed: {}".format(e))

    if database_ready:
        try:
            reclaimed = agent_api.reclaim_portal_agents(_portal_node_id())
            print("[server] Reclaimed {} Portal Agent(s) owned by this node".format(reclaimed))
        except Exception as e:
            print("[server] WARNING: Portal Agent recovery failed: {}".format(e))

    try:
        from lib.config import get_config
        emb_cfg = get_config().embedding
        if not emb_cfg.model or not emb_cfg.api_url:
            print("[server] WARNING: Embedding model not configured (embedding.api_url/model in config.json)")
            print("[server]          Vector search will be unavailable until configured.")
        else:
            print("[server] Embedding: {} (dim={})".format(emb_cfg.model, emb_cfg.dimension or "auto"))
    except Exception:
        pass

    server = ThreadingHTTPServer((host, port), VisHandler)
    print("[server] AI Agent Infra v{} Community Edition visualization server".format(VERSION))
    print("[server] Listening on http://{}:{}".format(host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] Shutting down")
        server.server_close()
        connection.close_pool()


if __name__ == '__main__':
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    main()

# v3.7.5 Handler methods (appended)
# These are stub implementations that delegate to the API modules
