from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v414_clean_evidence_is_bound_to_real_release_artifacts():
    source = (ROOT / "tools/v414_clean_deployment_evidence.py").read_text(encoding="utf-8")

    assert "package_manifest_sha256" in source
    assert "archive_package_index_bound" in source
    assert "82_v4_4_14_governed_model_capabilities.sql" in source
    assert "clean_before_deploy" in source
    assert "INITIAL_USER_OBJECTS" in source
