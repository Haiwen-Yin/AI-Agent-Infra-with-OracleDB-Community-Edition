"""Logout revokes authentication before releasing the Portal connection slot."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_portal_logout_releases_only_its_connection():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "web_app.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "logout")
    node.decorator_list = []
    node.returns = None
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None
    calls = []
    identity = SimpleNamespace(
        revoke_session=lambda token, reason: calls.append(("revoke", token)),
        release_portal_connection=lambda token, reason: calls.append(("release", token)))
    response = Mock()
    namespace = {"identity_api": identity, "JSONResponse": lambda _: response,
                 "_session_scope_for_path": lambda _: "PORTAL",
                 "_cookie_name": lambda scope, port: scope,
                 "Dict": dict, "Any": object}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(root / "web_app.py"), "exec"), namespace)
    request = SimpleNamespace(url=SimpleNamespace(path="/portal/api/auth/logout", port=8000),
                              cookies={"PORTAL": "portal-session", "DASHBOARD": "dashboard-session"})
    namespace["logout"](request, {})
    assert calls == [("revoke", "portal-session"), ("release", "portal-session"), ("revoke", "dashboard-session")]
    assert response.delete_cookie.call_count == 2
