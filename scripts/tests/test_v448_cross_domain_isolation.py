from typing import Any

import pytest

from lib import identity_api


class BridgeTx:
    def __init__(self, source_level: str, target_level: str):
        self.source_level = source_level
        self.target_level = target_level

    def query_one(self, sql: str, params: dict[str, Any]):
        if "FROM CX_BRIDGES" in sql:
            return {
                "bridge_id": "BR_1", "source_domain_id": "DOMAIN_A",
                "target_domain_id": "DOMAIN_B", "transfer_mode": "REFERENCE",
                "classification": "INTERNAL", "status": "APPROVED",
                "expires_at": "2999-01-01T00:00:00Z",
            }
        if "FROM CX_DOMAIN_MEMBERS" in sql:
            return {"membership_id": "MEMBER_1"}
        return None

    def query(self, sql: str, params: dict[str, Any]):
        if "FROM CX_SECURITY_DOMAINS" in sql:
            return [
                {"security_domain_id": "DOMAIN_A", "classification": self.source_level},
                {"security_domain_id": "DOMAIN_B", "classification": self.target_level},
            ]
        return []

    def execute(self, sql: str, params: dict[str, Any]):
        return 1


@pytest.fixture
def bridge_actor(monkeypatch):
    monkeypatch.setattr(identity_api, "_require", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(identity_api, "effective_access", lambda *_args, **_kwargs: {"decision": "DENY"})
    monkeypatch.setattr(
        identity_api.connection, "execute_transaction_callback",
        lambda work: work(BridgeTx("RESTRICTED", "INTERNAL")),
    )
    import datetime as dt
    monkeypatch.setattr(identity_api, "_now", lambda: dt.datetime(2000, 1, 1))


def test_bridge_transfer_enforces_classification_ceiling(bridge_actor):
    with pytest.raises(identity_api.IdentityError, match="classification ceiling"):
        identity_api.create_bridge_transfer(
            "admin", "BR_1", "MEMORY_VERSION", "MV_1", "approved cross-domain work",
        )
