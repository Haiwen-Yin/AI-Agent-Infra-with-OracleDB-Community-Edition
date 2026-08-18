"""PostgreSQL pool compatibility and bounded-wait contracts."""

from __future__ import annotations

from pathlib import Path
import json
import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MODE = (ROOT / "build-manifest.json").is_file() and not (ROOT / "adapters").is_dir()
DATABASE_KEY = (
    str(json.loads((ROOT / "build-manifest.json").read_text(encoding="ascii"))["database"]["key"])
    if PACKAGE_MODE else "pg"
)


def _source_path(name: str) -> Path:
    if PACKAGE_MODE:
        return ROOT / "scripts" / "lib" / name
    source_name = "config_db.py" if name == "config.py" else name
    return ROOT / "adapters" / "pg" / source_name


def test_pg_adapter_accepts_legacy_edition_pool_configuration_names():
    if DATABASE_KEY != "pg":
        pytest.skip("PostgreSQL adapter contract is validated by the PG package")
    source = _source_path("config.py").read_text(encoding="utf-8")
    assert 'db_resolved.get("pool_min"' in source
    assert 'db_resolved.get("pool_max"' in source


def test_pg_adapter_waits_within_the_configured_pool_ceiling():
    if DATABASE_KEY != "pg":
        pytest.skip("PostgreSQL adapter contract is validated by the PG package")
    source = _source_path("connection.py").read_text(encoding="utf-8")
    assert "threading.BoundedSemaphore(db_cfg.max_conn)" in source
    assert "slots.acquire(timeout=_POOL_WAIT_SECONDS)" in source
    assert "pool.putconn(conn)" in source
