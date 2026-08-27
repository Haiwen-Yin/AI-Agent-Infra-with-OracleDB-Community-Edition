from typing import Any

import pytest

from lib import isolation_inventory


class InventoryDb:
    def __init__(self):
        self.existing = set()
        self.inserted = []

    def query_one(self, sql, params):
        key = (params["object_type"], params["object_name"])
        return {"inventory_id": "exists"} if key in self.existing else None

    def execute(self, sql, params):
        self.inserted.append(params)
        self.existing.add((params["object_type"], params["object_name"]))
        return 1

    def execute_transaction_callback(self, work):
        return work(self)


def test_isolation_inventory_is_idempotent_and_non_overwriting():
    db = InventoryDb()
    original = isolation_inventory.connection
    isolation_inventory.connection = db
    try:
        first = isolation_inventory.ensure_isolation_inventory()
        assert first["inserted"] == len(isolation_inventory.INVENTORY)
        assert "derived" not in db.inserted[0]
        assert db.inserted[0]["inheritance"] == "SOURCE:NONE"
        assert db.inserted[0]["reason"] == "v4.4.10 database-authoritative isolation baseline"
        second = isolation_inventory.ensure_isolation_inventory()
        assert second["inserted"] == 0
    finally:
        isolation_inventory.connection = original


def test_isolation_inventory_covers_platform_knowledge_memory_and_graph():
    names = {item[1] for item in isolation_inventory.INVENTORY}
    assert {"CX_PLATFORM_KNOWLEDGE", "CX_MEMORY_VERSIONS", "GRAPH_RUNS", "CX_SECURITY_DOMAINS"} <= names


def test_inventory_listing_requires_platform_management(monkeypatch):
    monkeypatch.setattr(
        isolation_inventory.identity_api, "effective_access",
        lambda *_args, **_kwargs: {"decision": "DENY"},
    )
    with pytest.raises(PermissionError):
        isolation_inventory.list_isolation_inventory("user")
