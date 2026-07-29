"""Verify that the YashanDB pool uses the remote-driver connection contract."""

from types import SimpleNamespace

import pytest


def test_yashandb_pool_uses_keyword_connection_arguments(monkeypatch):
    from lib import connection

    if connection.DATABASE_DIALECT != "yashandb":
        pytest.skip("YashanDB adapter only")

    calls = []

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(connection.yaspy, "Connection", FakeConnection)
    cfg = SimpleNamespace(user="AIADMIN", password="secret", dsn="db.example:1688/PDB", pool_min=2, pool_max=4)
    pool = connection._init_pool(cfg)

    assert len(pool) == 2
    assert calls == [
        ((), {"user": "AIADMIN", "password": "secret", "dsn": "db.example:1688/PDB"}),
        ((), {"user": "AIADMIN", "password": "secret", "dsn": "db.example:1688/PDB"}),
    ]
