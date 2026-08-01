"""Live v4.3.2 memory lifecycle contract for generated database editions.

This suite is intentionally skipped in the unified source tree.  Each
generated Enterprise package supplies its concrete adapter and encrypted
baseline configuration, then runs the same lifecycle scenario against its
selected database.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from lib import memory_lifecycle as lifecycle


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    (PACKAGE_ROOT / "adapters").is_dir(),
    reason="live lifecycle checks require a generated database edition",
)


def _first_value(row):
    return next(iter(dict(row).values())) if row else None


def test_legacy_fusion_scheduler_is_not_active():
    """The old direct-mutating task must stay absent after the v4.3.2 upgrade."""
    dialect = str(getattr(lifecycle.connection, "DATABASE_DIALECT", "")).lower()
    if dialect in {"pg", "postgresql"}:
        catalog = lifecycle.execute_query_one("SELECT to_regclass('cron.job') AS cron_job", {})
        if not _first_value(catalog):
            return
        row = lifecycle.execute_query_one(
            "SELECT COUNT(*) AS job_count FROM cron.job WHERE jobname = :job_name",
            {"job_name": "memory_fusion_job"},
        )
    else:
        row = lifecycle.execute_query_one(
            "SELECT COUNT(*) AS job_count FROM USER_SCHEDULER_JOBS WHERE JOB_NAME = :job_name",
            {"job_name": "MEMORY_FUSION_JOB"},
        )
    assert int(_first_value(row) or 0) == 0


def test_versioned_memory_lifecycle_round_trip():
    marker = f"v432-live-{uuid.uuid4().hex[:12]}"
    actor = "admin"
    first = lifecycle.create_family(
        {
            "title": f"{marker} source",
            "body": "The approved runtime boundary is database-authoritative.",
            "memory_type": "DECISION",
            "memory_scope": "RUNTIME_CONTEXT",
            "classification": "INTERNAL",
            "reason": "live lifecycle verification",
        },
        actor=actor,
        idempotency_key=f"{marker}-family",
    )
    family_id = first["family_id"]
    first_version_id = first["version_id"]

    family = lifecycle.get_family(family_id, include_history=True)
    assert family and family["current"]["version_id"] == first_version_id
    assert family["current"]["version_number"] == 1

    successor = lifecycle.create_successor(
        family_id,
        first_version_id,
        {
            "title": f"{marker} current",
            "body": "The approved runtime boundary remains database-authoritative and auditable.",
            "memory_type": "DECISION",
            "memory_scope": "RUNTIME_CONTEXT",
            "classification": "INTERNAL",
            "reason": "live successor verification",
        },
        actor=actor,
        idempotency_key=f"{marker}-successor",
    )
    current_version_id = successor["version_id"]
    assert successor["version_number"] == 2

    with pytest.raises(lifecycle.MemoryLifecycleError, match="refresh before retrying") as conflict:
        lifecycle.create_successor(
            family_id,
            first_version_id,
            {"title": f"{marker} stale", "body": "This write must not apply."},
            actor=actor,
        )
    assert conflict.value.code == "VERSION_CONFLICT"

    representation_id = lifecycle.create_deterministic_summary(current_version_id, token_budget=64)
    representations = lifecycle.create_deterministic_representations(current_version_id, token_budget=64)
    assert len(representations) == 4
    relation_id = lifecycle.create_relation(
        first_version_id,
        current_version_id,
        "DERIVED_FROM",
        deterministic=True,
        confidence=1.0,
        evidence={"verification": marker},
        actor=actor,
    )
    chain = lifecycle.chain(current_version_id, hops=2, limit=20)
    assert relation_id in {item["relation_id"] for item in chain["relations"]}
    assert {first_version_id, current_version_id}.issubset({item["version_id"] for item in chain["nodes"]})

    candidate = lifecycle.create_candidate(
        "REPLACE",
        current_version_id,
        {"representation_id": representation_id, "reason": "human review required"},
        actor=actor,
        confidence=0.9,
        reason="live candidate verification",
        idempotency_key=f"{marker}-candidate",
    )
    assert candidate["policy_result"] == "REVIEW"
    assert lifecycle.review_candidate(candidate["candidate_id"], "APPROVE", reviewer=actor, reason="verified")
    activated = lifecycle.activate_candidate(
        candidate["candidate_id"], actor=actor, reason="approved live activation verification",
    )
    current_version_id = activated["version_id"]
    assert activated["status"] == "ACTIVATED"

    job = lifecycle.create_job(
        "CONSOLIDATE",
        actor=actor,
        scope={"family_id": family_id},
        dry_run=True,
        reason="live job verification",
        idempotency_key=f"{marker}-job",
    )
    assert any(item["job_id"] == job["job_id"] for item in lifecycle.list_jobs())
    assert lifecycle.record_usage(
        current_version_id,
        "RETRIEVED",
        principal_id=actor,
        run_id=f"{marker}-run",
        outcome="HELPFUL",
        idempotency_key=f"{marker}-usage",
    )

    snapshot = lifecycle.create_snapshot(
        f"{marker}-run",
        actor=actor,
        purpose="RUNTIME_CONTEXT",
        token_budget=256,
        idempotency_key=f"{marker}-snapshot",
    )
    assert snapshot["members"] >= 1
    refreshed = lifecycle.refresh_snapshot(
        snapshot["snapshot_id"], actor=actor, token_budget=256,
        reason="live refresh verification", idempotency_key=f"{marker}-refresh",
    )
    assert refreshed["refreshed_from"] == snapshot["snapshot_id"]

    unavailable = lifecycle.mark_unavailable(
        family_id,
        actor=actor,
        reason="live verification cleanup: retain evidence but exclude retrieval",
        expected_version_id=current_version_id,
    )
    assert unavailable["lifecycle_state"] == "UNAVAILABLE"
    assert not lifecycle.current_memories(keyword=marker, limit=20)
    diff = lifecycle.snapshot_diff(refreshed["snapshot_id"])
    assert any(item["family_id"] == family_id for item in diff["changed"])
