"""Pure tests for the unified Graph governance event document."""

from lib.graph_governance import governance_event_document


def test_governance_event_document_is_bounded_and_redacted_recursively():
    document = governance_event_document(
        "NODE_COMPLETED", "agent-1", "completed",
        run_id="run-1",
        detail={
            "nested": {"api_key": "do-not-store", "visible": "ok"},
            "items": [{"authorization": "hidden"}],
        },
    )
    assert document["event_type"] == "NODE_COMPLETED"
    assert document["detail"]["nested"]["api_key"] == "[REDACTED]"
    assert document["detail"]["nested"]["visible"] == "ok"
    assert document["detail"]["items"][0]["authorization"] == "[REDACTED]"
    assert len(document["detail_hash"]) == 64
