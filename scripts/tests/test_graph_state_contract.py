"""Pure tests for the v4.2 Graph state disclosure boundary."""

from lib.graph_state import (
    prepare_output,
    project_state,
    redact_state,
    validate_artifact_references,
)


def test_redaction_is_recursive_for_nested_worker_payloads():
    value = {
        "public": {"answer": "ok"},
        "metadata": [{"access_token": "do-not-store"}],
        "credentials": {"password": "hidden"},
    }
    redacted = redact_state(value)
    assert redacted["public"]["answer"] == "ok"
    assert redacted["metadata"][0]["access_token"] == "[REDACTED]"
    assert redacted["credentials"] == "[REDACTED]"


def test_project_state_obeys_explicit_allow_list_and_schema():
    projected, errors = project_state(
        {
            "public": "ok",
            "private": "must-not-cross-worker-boundary",
            "profile": {"name": "agent", "password": "secret"},
        },
        {
            "type": "object",
            "required": ["public", "profile"],
            "properties": {
                "public": {"type": "string"},
                "profile": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        },
        {"state_fields": ["public", "profile.name"]},
    )
    assert errors == []
    assert projected == {"public": "ok", "profile": {"name": "agent"}}


def test_output_requires_schema_and_references_artifacts_without_payloads():
    schema = {
        "type": "object",
        "required": ["result", "artifact_refs"],
        "properties": {
            "result": {"type": "string"},
            "artifact_refs": {"type": "array"},
        },
    }
    output, errors = prepare_output(
        {
            "result": "ok",
            "artifact_refs": [{"artifact_id": "ART_1", "content_hash": "abc", "content_size": 3}],
        },
        schema,
    )
    assert errors == []
    assert output["result"] == "ok"

    _, inline_errors = prepare_output(
        {"result": "ok", "artifact_refs": [{"artifact_id": "ART_1", "content": "raw"}]},
        schema,
    )
    assert any(item["code"] == "ARTIFACT_INLINE_CONTENT_FORBIDDEN" for item in inline_errors)


def test_output_size_is_bounded_before_checkpoint():
    _, errors = prepare_output({"result": "x" * 64}, {"type": "object"}, max_bytes=32)
    assert any(item["code"] == "OUTPUT_SIZE_EXCEEDED" for item in errors)


def test_artifact_reference_validator_rejects_missing_identity():
    errors = validate_artifact_references({"artifact_refs": [{"content_size": 0}]})
    assert {item["code"] for item in errors} >= {"ARTIFACT_REF_FIELD_MISSING"}
