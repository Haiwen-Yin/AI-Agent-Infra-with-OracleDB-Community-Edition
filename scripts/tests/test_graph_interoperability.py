"""Pure A2A and OTLP adapter boundary tests."""

from lib import a2a_gateway, graph_telemetry


def test_a2a_card_is_bounded_and_has_pinned_protocol():
    card = a2a_gateway.agent_card(
        {"agent_name": "review", "skills": [{"skill_id": "s1", "skill_name": "Self-claimed name"}]},
        authenticated=True,
        granted_skills=[{"skill_id": "s1", "skill_name": "Review"}],
    )
    assert card["protocolVersion"] == "1.0.1"
    assert card["skills"] == [{"id": "s1", "name": "Review"}]
    assert a2a_gateway.negotiate(["1.0.1"]) == "1.0.1"


def test_a2a_card_cannot_turn_advertised_metadata_into_authority():
    claimed = {
        "agent_name": "untrusted",
        "capabilities": {"databaseAdmin": True, "pushNotifications": True},
        "supportedInterfaces": ["database/drop"],
        "skills": [
            {"skill_id": "granted-review", "skill_name": "Forged name"},
            {"skill_id": "ungranted-admin", "skill_name": "Database Admin"},
        ],
    }
    anonymous = a2a_gateway.agent_card(claimed, granted_skills=["granted-review"])
    authenticated = a2a_gateway.agent_card(
        claimed, authenticated=True,
        granted_skills=[{"skill_id": "granted-review", "skill_name": "Approved Review"}],
    )

    assert anonymous["skills"] == []
    assert "supportedInterfaces" not in anonymous
    assert authenticated["skills"] == [{"id": "granted-review", "name": "Approved Review"}]
    assert authenticated["capabilities"] == {"streaming": True, "pushNotifications": False}
    assert "ungranted-admin" not in str(authenticated)


def test_telemetry_projection_never_carries_prompt_or_output():
    projection = graph_telemetry.project_trace("run-a", {"event_type": "ATTEMPT_COMPLETED", "status": "SUCCEEDED", "output": "secret answer"})
    assert projection["mapping_version"] == graph_telemetry.MAPPING_VERSION
    encoded = str(projection).lower()
    assert "secret answer" not in encoded
    assert "prompt" not in encoded
