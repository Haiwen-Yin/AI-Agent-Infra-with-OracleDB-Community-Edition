"""Oracle native Property Graph adapter boundary."""

from typing import Any, Dict, List, Optional, Tuple

try:
    from .graph_predicate import compile_safe_predicate, state_ref
except ImportError:  # source-tree adapter probe
    from lib.graph_predicate import compile_safe_predicate, state_ref

NATIVE_GRAPH_NAME = "ORACLE_EXECUTION_GRAPH"


def projection_statements(version_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Tuple[str, Optional[Dict[str, Any]]]]:
    # Oracle SQL/PGQ reads the dedicated relational tables directly.  No
    # duplicate vertex/edge rows are needed in a separate projection.
    return []


def capability_probe() -> Dict[str, Any]:
    return {
        "native_graph": True, "graph_name": NATIVE_GRAPH_NAME, "adapter": "oracle-sql-pgq",
        "predicate_pushdown": {"dialect": "oracle-json", "fallback": "portable-evaluator"},
    }


def compile_predicate(expression: Any) -> Dict[str, Any]:
    """Compile the safe subset against Oracle JSON state properties."""
    def resolve(ref: str) -> Optional[str]:
        parts = state_ref(ref)
        if not parts:
            return None
        path = "$." + ".".join(parts)
        return "JSON_VALUE(STATE_JSON, '" + path + "')"

    return compile_safe_predicate(
        expression, dialect="oracle-json", resolve_ref=resolve,
        placeholder=lambda name: ":" + name,
    )
