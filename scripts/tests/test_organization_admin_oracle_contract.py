from pathlib import Path


def test_admin_change_inventory_does_not_bind_actor_for_global_scope():
    source = (Path(__file__).resolve().parents[1] / "lib" / "organization_api.py").read_text(encoding="utf-8")
    block = source.split("def list_changes(", 1)[1].split("def get_change_set(", 1)[0]
    assert 'params: Dict[str, Any] = {"limit": _bounded(limit)}' in block
    assert 'params["actor"] = actor_principal_id' in block
