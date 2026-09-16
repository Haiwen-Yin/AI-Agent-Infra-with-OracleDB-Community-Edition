"""Portal failed admission must not consume the user's only connection slot."""
import ast
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from lib import identity_api


@pytest.mark.parametrize('status', ['ACTIVE', 'DISABLED', None])
@pytest.mark.parametrize('active', [0, 1])
def test_portal_admission_locks_identity_before_counting(monkeypatch, status, active):
    calls = []
    class Tx:
        def query_one(self, sql, params):
            if 'CX_PRINCIPALS' in sql:
                assert 'FOR UPDATE' in sql
                calls.append('identity')
                return {'status': status} if status else None
            assert calls == ['identity']
            calls.append('count')
            return {'cnt': active}
        def execute(self, sql, params):
            calls.append('insert')
    monkeypatch.setattr(identity_api.connection, 'execute_transaction_callback', lambda fn: fn(Tx()))
    monkeypatch.setattr(identity_api, '_portal_connection_limit', lambda *args: 1)
    if status != 'ACTIVE' or active:
        with pytest.raises(identity_api.IdentityError):
            identity_api.acquire_portal_connection('human', 'session', 'client', 'node')
        assert 'insert' not in calls
    else:
        assert identity_api.acquire_portal_connection('human', 'session', 'client', 'node')['connection_id']
        assert calls == ['identity', 'count', 'insert']


@pytest.mark.parametrize('failure', ['no_agent', 'agent_exception', 'page_conflict', 'page_unavailable'])
def test_failed_login_releases_connection_and_session(failure):
    # Execute the actual handler with transport and database boundaries replaced.
    # Importing the legacy server would start unrelated runtime initialization.
    path = Path(__file__).resolve().parents[1] / 'visualization/server.py'
    method = next(node for node in ast.walk(ast.parse(path.read_text()))
                  if isinstance(node, ast.FunctionDef) and node.name == '_handle_portal_login')
    identity = SimpleNamespace(
        IdentityError=identity_api.IdentityError,
        authenticate_local=Mock(return_value={'principal_id': 'human', 'username': 'admin', 'user_id': 'u'}),
        entry_allowed=Mock(return_value=True),
        acquire_portal_connection=Mock(return_value={'connection_id': 'connection'}),
        acquire_portal_page_lease=Mock(return_value={'lease_id': 'page'}),
        release_portal_connection=Mock(), revoke_session=Mock(),
    )
    if failure.startswith('page_'):
        identity.acquire_portal_page_lease.side_effect = (identity_api.IdentityError('conflict')
            if failure == 'page_conflict' else RuntimeError('unavailable'))
    agents = Mock(return_value=None)
    if failure == 'agent_exception':
        agents.side_effect = RuntimeError('unavailable')
    sessions = {'session': {}}
    namespace = dict(json=json, identity_api=identity, sessions=sessions,
        logger=logging.getLogger(__name__),
        security_lifecycle=SimpleNamespace(is_login_locked=lambda _: False, mfa_required=lambda _: False,
            record_login_success=lambda _: None),
        governed_contracts=SimpleNamespace(mfa_admission_decision=lambda **_: SimpleNamespace(allowed=True)),
        _create_session=lambda *args, **kwargs: 'session', _portal_node_id=lambda: 'node',
        _session_timeout=lambda *args: 300, _get_or_assign_portal_agent=agents)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    handler = SimpleNamespace(_read_body=lambda: json.dumps({'username': 'admin', 'password': 'test'}),
                              headers={}, _send_json=Mock())
    namespace['_handle_portal_login'](handler)
    identity.release_portal_connection.assert_called_once()
    identity.revoke_session.assert_called_once()
    assert not sessions
    assert handler._send_json.call_args.args[0]['success'] is False
    assert handler._send_json.call_args.args[1] == (409 if failure == 'page_conflict' else 503)


@pytest.mark.parametrize('connection_expired', [True, False])
def test_expired_page_is_reclaimed_without_duplicate_insert(monkeypatch, connection_expired):
    now = datetime(2026, 9, 15, 12, 0)
    updates = []
    class Tx:
        def query_one(self, sql, params):
            if 'CX_PORTAL_CONNECTIONS' in sql:
                assert 'FOR UPDATE' in sql
                return {'connection_id': 'c', 'lease_expires_at': now + timedelta(seconds=-1 if connection_expired else 60)}
            return {'lease_id': 'p', 'page_instance_digest': 'old', 'fencing_token': 4,
                    'status': 'ACTIVE', 'lease_expires_at': now - timedelta(seconds=1)}
        def execute(self, sql, params):
            assert sql.startswith('UPDATE CX_PORTAL_PAGE_LEASES')
            updates.append(params)
    monkeypatch.setattr(identity_api, '_now', lambda: now)
    monkeypatch.setattr(identity_api.connection, 'execute_transaction_callback', lambda fn: fn(Tx()))
    if connection_expired:
        with pytest.raises(identity_api.IdentityError, match='connection is unavailable'):
            identity_api.acquire_portal_page_lease('session', 'new')
        assert not updates
    else:
        result = identity_api.acquire_portal_page_lease('session', 'new')
        assert result['lease_id'] == 'p'
        assert result['fencing_token'] == 5
        assert updates[0]['expires_at'] == now + timedelta(seconds=60)


def test_expired_connection_heartbeat_uses_issuance_clock(monkeypatch):
    now = datetime(2026, 9, 15, 12, 0)
    def execute(sql, params):
        assert 'LEASE_EXPIRES_AT > :now' in sql
        assert 'CURRENT_TIMESTAMP' not in sql
        assert params['now'] == now
        assert params['expires_at'] == now + timedelta(seconds=300)
        return 0
    monkeypatch.setattr(identity_api, '_now', lambda: now)
    monkeypatch.setattr(identity_api.connection, 'execute', execute)
    assert identity_api.heartbeat_portal_connection('expired') is False
