"""Pure v4.2.1 release-closure and generated-package guard tests."""

from pathlib import Path
import zipfile

from lib.graph_compat import capability_definition
from package_guard import forbidden_package_paths, verify_archive, verify_manifest, write_manifest
from release_closure import build_manifest


def test_release_closure_is_not_releasable_without_mandatory_evidence():
    manifest = build_manifest(release_date="2026-07-27")
    assert manifest["releasable"] is False
    assert all(item["mandatory"] for item in manifest["gates"])
    assert {item["status"] for item in manifest["gates"]} == {"UNVERIFIED"}


def test_release_closure_can_become_releasable_only_when_every_gate_passes():
    from release_closure import GATES

    evidence = {
        gate_id: {"status": "PASS", "source": "test"}
        for gate_id, _, _ in GATES
    }
    manifest = build_manifest(release_date="2026-07-27", evidence=evidence)
    assert manifest["releasable"] is True


def test_generated_package_guard_detects_post_build_edits(tmp_path: Path):
    (tmp_path / "README.md").write_text("generated\n", encoding="utf-8")
    write_manifest(tmp_path)
    assert verify_manifest(tmp_path) == []
    (tmp_path / "README.md").write_text("edited\n", encoding="utf-8")
    assert any("changed README.md" in item for item in verify_manifest(tmp_path))


def test_generated_archive_guard_detects_missing_or_changed_files(tmp_path: Path):
    root = tmp_path / "package"
    root.mkdir()
    (root / "README.md").write_text("generated\n", encoding="utf-8")
    write_manifest(root)
    archive_path = tmp_path / "package.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, f"{root.name}/{path.relative_to(root).as_posix()}")
    assert verify_archive(root, archive_path) == []
    (root / "README.md").write_text("edited\n", encoding="utf-8")
    assert any("archive content differs" in item for item in verify_archive(root, archive_path))


def test_package_guard_rejects_runtime_and_secret_paths(tmp_path: Path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "app.log").write_text("runtime\n", encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    assert set(forbidden_package_paths(tmp_path)) == {"config.json", "logs", "logs/app.log"}


def test_build_manifest_records_source_commit(tmp_path: Path):
    import json
    package_root = Path(__file__).resolve().parents[2]
    if (package_root / "build.py").is_file():
        import build
        build.write_build_manifest(
            tmp_path, "pg", "PostgreSQL", "Community", "4.4.9", {}, {}, "production"
        )
        manifest_path = tmp_path / "build-manifest.json"
    else:
        manifest_path = package_root / "build-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    assert manifest["source_commit"]


def test_capability_wrappers_share_one_declarative_graph_shape():
    definition = capability_definition("TOOL", "tool-1", "TOOL", {"version": "2.0"})
    assert [node["node_key"] for node in definition["nodes"]] == ["start", "tool:tool-1", "end"]
    assert definition["nodes"][1]["config"]["legacy_kind"] == "TOOL"
    assert all("handler" not in node.get("config", {}) for node in definition["nodes"])
