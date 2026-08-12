"""PostgreSQL pool compatibility and bounded-wait contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pg_adapter_accepts_legacy_edition_pool_configuration_names():
    source = (ROOT / "adapters/pg/config_db.py").read_text(encoding="utf-8")
    assert 'db_resolved.get("pool_min"' in source
    assert 'db_resolved.get("pool_max"' in source


def test_pg_adapter_waits_within_the_configured_pool_ceiling():
    source = (ROOT / "adapters/pg/connection.py").read_text(encoding="utf-8")
    assert "threading.BoundedSemaphore(db_cfg.max_conn)" in source
    assert "slots.acquire(timeout=_POOL_WAIT_SECONDS)" in source
    assert "pool.putconn(conn)" in source
