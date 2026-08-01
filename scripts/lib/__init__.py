"""AI Agent Infra core library.

Submodules are intentionally loaded on demand so edition builds can physically
exclude capabilities without package-import side effects.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_selected_adapter() -> None:
    """Overlay adapter modules only for explicit source-tree DB tests.

    Normal source imports remain side-effect free.  Setting
    ``AIAGENT_SOURCE_ADAPTER`` is an opt-in test/development mode; packaged
    editions do not need it because ``build.py`` physically copies the same
    adapter files over the facades.
    """
    name = str(os.environ.get("AIAGENT_SOURCE_ADAPTER", "")).strip().lower()
    if name not in {"oracle", "pg", "yashandb"}:
        return
    root = Path(__file__).resolve().parents[2] / "adapters" / name
    if not root.is_dir():
        raise RuntimeError(f"source adapter directory does not exist: {root}")
    for module_name, filename in (("config", "config_db.py"), ("connection", "connection.py"), ("agent_api", "agent_api.py")):
        module_key = f"{__name__}.{module_name}"
        if module_key in sys.modules:
            continue
        path = root / filename
        spec = importlib.util.spec_from_file_location(module_key, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load source adapter module: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        setattr(sys.modules[__name__], module_name, module)
        spec.loader.exec_module(module)


_load_selected_adapter()
