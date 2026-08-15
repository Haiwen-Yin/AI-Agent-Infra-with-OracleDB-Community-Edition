from pathlib import Path

from tools.validate_release_claims import validate_manifest


def test_release_claims_require_evidence_beyond_source_or_checkboxes(tmp_path):
    manifest = tmp_path / "release.json"
    manifest.write_text(
        '{"schema":"ai-agent-infra-release-evidence/v1","version":"4.4.5",'
        '"release_date":"2026-08-15","tasks":["all checked"]}',
        encoding="utf-8",
    )
    result = validate_manifest(tmp_path, manifest, expected_version="4.4.5")
    assert result["passed"] is False
    assert any("required evidence missing" in error for error in result["errors"])
