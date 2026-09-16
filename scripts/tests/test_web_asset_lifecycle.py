"""A serving process must survive removal of a package test compatibility link."""
import ast
from pathlib import Path


def test_asset_paths_survive_compatibility_link_removal(tmp_path):
    # Execute the production path selection without booting database workers.
    source = Path(__file__).resolve().parents[1] / 'web_app.py'
    tree = ast.parse(source.read_text())
    nodes = []
    active = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'WEB_ROOT' for t in node.targets):
            active = True
        if active:
            nodes.append(node)
        if active and isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DIST_ROOT' for t in node.targets):
            break
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    assets = tmp_path / 'web' / 'dist'
    assets.mkdir(parents=True)
    (assets / 'index.html').write_text('synthetic shell')
    link = scripts / 'web'
    link.symlink_to('../web', target_is_directory=True)
    namespace = {'Path': Path, '__file__': str(scripts / 'web_app.py')}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    link.unlink()
    assert (namespace['DIST_ROOT'] / 'index.html').read_text() == 'synthetic shell'
    assert namespace['WEB_ROOT'] == tmp_path / 'web'
