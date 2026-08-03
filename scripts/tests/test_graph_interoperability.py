"""Pure A2A and OTLP adapter boundary tests."""

from lib import a2a_gateway, graph_telemetry


def test_a2a_card_is_bounded_and_has_pinned_protocol():
    card = a2a_gateway.agent_card({"agent_name": "review", "skills": [{"skill_id": "s1", "skill_name": "Review"}]})
    assert card["protocolVersion"] == "1.0.1"
    assert card["skills"] == [{"id": "s1", "name": "Review"}]
    assert a2a_gateway.negotiate(["1.0.1"]) == "1.0.1"


def test_telemetry_projection_never_carries_prompt_or_output():
    projection = graph_telemetry.project_trace("run-a", {"event_type": "ATTEMPT_COMPLETED", "status": "SUCCEEDED", "output": "secret answer"})
    assert projection["mapping_version"] == graph_telemetry.MAPPING_VERSION
    encoded = str(projection).lower()
    assert "secret answer" not in encoded
    assert "prompt" not in encoded
