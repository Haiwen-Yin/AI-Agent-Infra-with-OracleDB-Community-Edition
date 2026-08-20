import json

from tools.version_consistency import validate_version_consistency


def test_version_consistency_accepts_current_source(tmp_path):
    (tmp_path / "VERSION").write_text("4.4.9\n", encoding="ascii")
    package = tmp_path / "shared" / "web"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": "4.4.9"}), encoding="utf-8")
    assert validate_version_consistency(tmp_path, "4.4.9", {"version": "4.4.9"}) == []


def test_version_consistency_rejects_frontend_drift(tmp_path):
    (tmp_path / "VERSION").write_text("4.4.9\n", encoding="ascii")
    package = tmp_path / "shared" / "web"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": "4.4.7"}), encoding="utf-8")
    assert "frontend package version does not match VERSION" in validate_version_consistency(tmp_path, "4.4.9")


def test_version_consistency_accepts_generated_package_layout(tmp_path):
    (tmp_path / "VERSION").write_text("4.4.9\n", encoding="ascii")
    package = tmp_path / "web"
    package.mkdir()
    (package / "package.json").write_text(json.dumps({"version": "4.4.9"}), encoding="utf-8")
    assert validate_version_consistency(tmp_path, "4.4.9", {"version": "4.4.9"}) == []
