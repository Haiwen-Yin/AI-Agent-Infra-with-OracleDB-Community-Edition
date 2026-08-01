"""Safe, portable predicate compilation for Graph Engineering adapters.

The compiler remains the semantic authority.  This module only translates a
small, parameterized expression subset for an adapter that can prove parity
with the common evaluator; unsupported expressions must use the portable
evaluator instead of being interpolated into database or Cypher text.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


_SUPPORTED_OPS = frozenset({
    "and", "or", "not", "eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null",
    "literal", "ref",
})
_REF_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ROOTS = frozenset({"state", "node", "budget", "run", "event"})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _validate_reference(value: Any) -> Optional[str]:
    ref = str(value or "")
    parts = ref.split(".")
    if len(parts) < 2 or parts[0] not in _ROOTS or any(not _REF_PART.fullmatch(part) for part in parts[1:]):
        return None
    return ref


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def compile_safe_predicate(
    expression: Any,
    *,
    dialect: str,
    resolve_ref: Callable[[str], Optional[str]],
    placeholder: Callable[[str], str],
) -> Dict[str, Any]:
    """Compile a parameterized predicate without evaluating user SQL.

    ``resolve_ref`` is owned by each adapter and may return only a known
    physical column/property expression.  Values are always returned in the
    separate ``params`` mapping.  The result is deliberately descriptive so
    the caller can record a fallback decision as evidence.
    """
    from .graph_compiler import validate_expression_ast

    diagnostics = validate_expression_ast(expression, path="predicate")
    if diagnostics:
        return {
            "supported": False, "dialect": dialect, "sql": None, "params": {},
            "ast_digest": _digest(expression), "reason": "AST_INVALID", "diagnostics": diagnostics,
        }

    params: Dict[str, Any] = {}
    counter = [0]

    def bind(value: Any) -> str:
        name = f"p{counter[0]}"
        counter[0] += 1
        params[name] = value
        return placeholder(name)

    def render(node: Any) -> str:
        if not isinstance(node, dict):
            raise ValueError("PREDICATE_CHILD_INVALID")
        op = str(node.get("op") or "").lower()
        if op not in _SUPPORTED_OPS:
            raise ValueError("PREDICATE_OPERATOR_UNSUPPORTED")
        if op == "literal":
            value = node.get("value")
            if not _is_scalar(value):
                raise ValueError("PREDICATE_LITERAL_UNSUPPORTED")
            return bind(value)
        if op == "ref":
            ref = _validate_reference(node.get("path") or node.get("ref"))
            resolved = resolve_ref(ref) if ref else None
            if not resolved:
                raise ValueError("PREDICATE_REFERENCE_UNAVAILABLE")
            return resolved
        if op in {"and", "or"}:
            args = node.get("args")
            if not isinstance(args, list) or not args:
                raise ValueError("PREDICATE_ARITY")
            glue = " AND " if op == "and" else " OR "
            return "(" + glue.join(render(item) for item in args) + ")"
        if op == "not":
            args = node.get("args")
            if not isinstance(args, list) or len(args) != 1:
                raise ValueError("PREDICATE_ARITY")
            return "(NOT " + render(args[0]) + ")"
        if op == "is_null":
            value = node.get("value")
            return "(" + render(value) + " IS NULL)"
        if op == "in":
            left = render(node.get("left"))
            right = node.get("right")
            if not isinstance(right, dict) or str(right.get("op") or "").lower() != "literal":
                raise ValueError("PREDICATE_IN_REQUIRES_LITERAL_ARRAY")
            values = right.get("value")
            if not isinstance(values, list) or not values or len(values) > 100:
                raise ValueError("PREDICATE_IN_VALUES_INVALID")
            if not all(_is_scalar(item) for item in values):
                raise ValueError("PREDICATE_LITERAL_UNSUPPORTED")
            return "(" + left + " IN (" + ", ".join(bind(item) for item in values) + "))"
        operators = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        left = node.get("left")
        right = node.get("right")
        return "(" + render(left) + " " + operators[op] + " " + render(right) + ")"

    try:
        sql = render(expression)
    except ValueError as exc:
        return {
            "supported": False, "dialect": dialect, "sql": None, "params": {},
            "ast_digest": _digest(expression), "reason": str(exc), "diagnostics": [],
        }
    return {
        "supported": True, "dialect": dialect, "sql": sql, "params": params,
        "ast_digest": _digest(expression), "reason": "SUPPORTED", "diagnostics": [],
    }


def state_ref(path: str) -> Optional[List[str]]:
    """Return validated State path parts for adapter-specific resolvers."""
    ref = _validate_reference(path)
    if not ref or not ref.startswith("state."):
        return None
    return ref.split(".")[1:]
