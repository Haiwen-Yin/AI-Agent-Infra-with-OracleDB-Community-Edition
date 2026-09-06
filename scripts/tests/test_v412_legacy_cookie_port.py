"""Compatibility handlers must use the same request port as FastAPI login."""

import ast
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import os
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]


def function(path, name, namespace):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.returns = None
    for arg in node.args.args:
        arg.annotation = None
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setenv('MEMORY_SERVER_PORT', '8000')
    port = ContextVar('test_cookie_port', default=None)
    cookie = function(ROOT / 'visualization/server.py', '_get_cookie_name', {
        'os': os, '_request_cookie_port': port,
        '_load_server_config': lambda: SimpleNamespace(port=8000),
    })
    run = function(ROOT / 'web_app.py', '_run_legacy_handler', {
        '_legacy_module': lambda: SimpleNamespace(_request_cookie_port=port),
    })
    return port, cookie, run


@pytest.mark.parametrize('scope', ['PORTAL', 'DASHBOARD'])
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_request_port_overrides_configuration_and_is_reset(bridge, scope, method):
    port, cookie, run = bridge
    seen = []
    handler = SimpleNamespace(_cx_cookie_port='18443',
                              do_GET=lambda: seen.append(cookie(scope)),
                              do_POST=lambda: seen.append(cookie(scope)))
    run(handler, method)
    assert seen == [scope.lower() + '_session_id_18443']
    assert port.get() is None
    assert cookie(scope) == scope.lower() + '_session_id_8000'


def test_failed_request_restores_context(bridge):
    port, _, run = bridge
    def fail():
        raise RuntimeError('synthetic failure')
    with pytest.raises(RuntimeError):
        run(SimpleNamespace(_cx_cookie_port='8001', do_GET=fail), 'GET')
    assert port.get() is None


def test_simultaneous_ports_do_not_share_context(bridge):
    _, cookie, run = bridge
    barrier = threading.Barrier(2)
    def request(port):
        seen = []
        def handle():
            barrier.wait(timeout=5)
            seen.append(cookie('DASHBOARD'))
        run(SimpleNamespace(_cx_cookie_port=port, do_GET=handle), 'GET')
        return seen[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(request, ['8001', '8443'])) == [
            'dashboard_session_id_8001', 'dashboard_session_id_8443',
        ]
