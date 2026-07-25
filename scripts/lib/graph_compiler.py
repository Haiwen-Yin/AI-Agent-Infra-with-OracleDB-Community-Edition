"""Deterministic, safe compiler for v4.2.x execution graphs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

COMPILER_VERSION = "4.2.0"
GRAPH_SCHEMA_VERSION = "1.0"
NODE_SIDE_EFFECT_CLASSES = frozenset({
    "NONE", "DB_TRANSACTIONAL", "IDEMPOTENT_EXTERNAL", "NON_IDEMPOTENT",
})
SAFE_AST_OPS = frozenset({
    "and", "or", "not", "eq", "ne", "gt", "gte", "lt", "lte",
    "in", "contains", "starts_with", "ends_with", "is_null", "add",
    "sub", "mul", "div", "literal", "ref",
})
REF_ROOTS = frozenset({"state", "node", "budget", "run", "event"})
FORBIDDEN_TERMS = frozenset({
    "python", "sql", "cypher", "shell", "file", "network", "environment",
    "credential", "secret", "import", "eval", "exec",
})
# ``eval`` and ``exec`` are execution syntax when they occur in a value, but
# they are also legitimate prefixes in governed metadata such as
# ``evaluation_config`` and ``executor``. Keep semantic capability names
# strict while checking execution syntax separately below.
FORBIDDEN_KEY_TERMS = FORBIDDEN_TERMS - {"eval", "exec"}
BUILTIN_NODES = frozenset({
    "START", "END", "AGENT", "MODEL", "LOOP", "SKILL", "TOOL", "DATABASE",
    "HTTP_API", "FUNCTION", "HUMAN", "TIMER", "EVENT", "SUBGRAPH", "CONTROL",
})
BUILTIN_DECISIONS = frozenset({
    "FIXED", "EXPRESSION", "RULES", "MODEL", "HUMAN", "EVENT", "ERROR", "TIMEOUT", "COMPENSATION",
})
EDGE_KINDS = frozenset({
    "NORMAL", "BRANCH", "FAN_OUT", "FAN_IN", "JOIN", "CYCLE", "EVENT",
    "ERROR", "TIMEOUT", "COMPENSATION", "SUBGRAPH", "FALLBACK",
})
JOIN_STRATEGIES = frozenset({"ALL", "ANY", "N_OF_M", "FIRST_SUCCESS", "QUORUM"})
HARD_BUDGET_KEYS = frozenset({
    "max_iterations", "max_calls", "max_tokens", "max_duration_seconds", "max_cost",
    "max_nodes", "max_retries", "max_concurrency", "max_external_calls",
})
RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _type_key(kind: str, name: str, version: str) -> str:
    return f"{str(kind).upper()}:{str(name)}:{str(version)}"


def builtin_type_registry() -> Dict[str, Dict[str, Any]]:
    """Return the immutable portable manifests used by the Compiler.

    The database registry may add compatible extensions, but it cannot replace
    these manifests silently.  Keeping the built-ins here also gives pure
    clients a deterministic validation surface before they connect to a DB.
    """
    nodes = {
        name: {"kind": "NODE", "name": name, "version": "1.0"}
        for name in BUILTIN_NODES
    }
    decisions = {
        name: {"kind": "DECISION", "name": name, "version": "1.0"}
        for name in BUILTIN_DECISIONS
    }
    reducers = {
        name: {"kind": "REDUCER", "name": name, "version": "1.0", "deterministic": True}
        for name in ("REPLACE", "APPEND", "SET_UNION", "SUM", "FIRST", "LAST")
    }
    result = {}
    for manifest in (*nodes.values(), *decisions.values(), *reducers.values()):
        result[_type_key(manifest["kind"], manifest["name"], manifest["version"])] = manifest
    return result


def _normalize_registry(registry: Any) -> Dict[str, Dict[str, Any]]:
    """Normalize list or keyed registry manifests without executing them."""
    result = builtin_type_registry()
    if isinstance(registry, dict):
        values = registry.values() if all(isinstance(v, dict) for v in registry.values()) else []
    elif isinstance(registry, (list, tuple)):
        values = registry
    else:
        values = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or raw.get("type_kind") or "").upper()
        name = str(raw.get("name") or raw.get("type_name") or "")
        version = str(raw.get("version") or raw.get("type_version") or "")
        if kind and name and version:
            result[_type_key(kind, name, version)] = dict(raw, kind=kind, name=name, version=version)
    return result


def _dependency_manifests(definition: Dict[str, Any], registry: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    resolved: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []
    dependencies = definition.get("dependencies") or definition.get("type_dependencies") or []
    if isinstance(dependencies, dict):
        dependencies = [dependencies]
    if not isinstance(dependencies, list):
        return [], [_diag("TYPE_DEPENDENCIES_INVALID", "dependencies must be an array", path="dependencies")]
    for index, raw in enumerate(dependencies):
        if not isinstance(raw, dict):
            diagnostics.append(_diag("TYPE_DEPENDENCY_INVALID", "dependency must be an object", path=f"dependencies[{index}]"))
            continue
        kind = str(raw.get("kind") or raw.get("type_kind") or "").upper()
        name = str(raw.get("name") or raw.get("type_name") or "")
        version = str(raw.get("version") or raw.get("type_version") or "")
        key = _type_key(kind, name, version)
        manifest = registry.get(key)
        if not kind or not name or not version or not manifest:
            diagnostics.append(_diag(
                "TYPE_DEPENDENCY_UNAVAILABLE",
                f"registered dependency is unavailable: {kind or '<kind>'}/{name or '<name>'}/{version or '<version>'}",
                path=f"dependencies[{index}]", kind=kind, name=name, version=version,
            ))
            continue
        resolved.append({"kind": kind, "name": name, "version": version, "manifest_digest": digest(manifest)})
    return resolved, diagnostics


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _diag(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    item = {"code": code, "message": message}
    item.update(extra)
    return item


def _node_key(node: Dict[str, Any]) -> str:
    return str(node.get("node_key") or node.get("id") or "")


def _edge_source(edge: Dict[str, Any]) -> str:
    return str(edge.get("source_node_key") or edge.get("source") or "")


def _edge_target(edge: Dict[str, Any]) -> str:
    return str(edge.get("target_node_key") or edge.get("target") or "")


def _normalize_node(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "node_key": _node_key(node),
        "node_type": str(node.get("node_type") or node.get("type") or "CONTROL").upper(),
        "type_version": str(node.get("type_version") or "1.0"),
        "config": node.get("config") or {},
        "input_schema": node.get("input_schema") or {},
        "output_schema": node.get("output_schema") or {},
        "side_effect_class": str(node.get("side_effect_class") or "NONE").upper(),
        "capabilities": node.get("capabilities") or [],
        "resource_scope": node.get("resource_scope") or {},
        "budget": node.get("budget") or {},
    }


def _normalize_edge(edge: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(edge.get("config") or {})
    if edge.get("join_strategy") and "join_strategy" not in config:
        config["join_strategy"] = edge["join_strategy"]
    if edge.get("reducer") and "reducer" not in config:
        config["reducer"] = edge["reducer"]
    return {
        "edge_id": str(edge.get("edge_id") or edge.get("id") or ""),
        "source_node_key": _edge_source(edge),
        "target_node_key": _edge_target(edge),
        "edge_kind": str(edge.get("edge_kind") or "NORMAL").upper(),
        "decision_type": str(edge.get("decision_type") or "FIXED").upper(),
        "condition": edge.get("condition") or {},
        "config": config,
        "order_index": int(edge.get("order_index") or 0),
        "join_key": edge.get("join_key"),
    }


def _contains_forbidden(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in FORBIDDEN_KEY_TERMS or any(term in key_text for term in FORBIDDEN_KEY_TERMS):
                return key_text
            found = _contains_forbidden(item)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _contains_forbidden(item)
            if found:
                return found
    elif isinstance(value, str):
        lowered = value.lower()
        for term in FORBIDDEN_TERMS:
            if lowered.startswith(term + ":") or lowered.startswith(term + "("):
                return term
        if re.search(r"\b(select|insert|update|delete|merge|create|drop|alter)\s+", lowered):
            return "sql"
        if re.search(r"\b(match|return|cypher)\s+", lowered):
            return "cypher"
        if re.search(r"\b(import|exec|eval|subprocess|socket)\s*[.(]", lowered):
            return "python"
    return None


def validate_expression_ast(expression: Any, path: str = "condition") -> List[Dict[str, Any]]:
    diagnostics: List[Dict[str, Any]] = []
    if expression in (None, {}, []):
        return diagnostics
    if not isinstance(expression, dict):
        return [_diag("EXPRESSION_NOT_OBJECT", f"{path} must be a typed AST object", path=path)]
    forbidden = _contains_forbidden(expression)
    if forbidden:
        diagnostics.append(_diag("EXPRESSION_FORBIDDEN", f"forbidden expression capability: {forbidden}", path=path))
        return diagnostics
    op = str(expression.get("op") or "").lower()
    if op not in SAFE_AST_OPS:
        diagnostics.append(_diag("EXPRESSION_OPERATOR_UNAVAILABLE", f"unsupported expression operator: {op or '<missing>'}", path=path))
        return diagnostics
    if op == "literal":
        if "value" not in expression:
            diagnostics.append(_diag("EXPRESSION_LITERAL_MISSING", "literal requires value", path=path))
        return diagnostics
    if op == "ref":
        ref = str(expression.get("path") or expression.get("ref") or "")
        if not ref or ref.split(".", 1)[0] not in REF_ROOTS:
            diagnostics.append(_diag("EXPRESSION_REF_SCOPE", "ref must start with an approved scope", path=path))
        return diagnostics
    children: List[Tuple[str, Any]] = []
    if "args" in expression:
        if not isinstance(expression["args"], list):
            diagnostics.append(_diag("EXPRESSION_ARGS", "args must be an array", path=path))
        else:
            children.extend((f"{path}.args[{i}]", value) for i, value in enumerate(expression["args"]))
    for key in ("left", "right", "value", "item", "set"):
        if key in expression:
            children.append((f"{path}.{key}", expression[key]))
    for child_path, child in children:
        if isinstance(child, dict) and "op" in child:
            diagnostics.extend(validate_expression_ast(child, child_path))
        elif not isinstance(child, (str, int, float, bool, type(None), list, tuple)):
            diagnostics.append(_diag("EXPRESSION_CHILD", "expression child has unsupported type", path=child_path))
    if op in {"and", "or"} and len(expression.get("args") or []) < 1:
        diagnostics.append(_diag("EXPRESSION_ARITY", f"{op} requires at least one argument", path=path))
    if op == "not" and len(expression.get("args") or []) != 1:
        diagnostics.append(_diag("EXPRESSION_ARITY", "not requires exactly one argument", path=path))
    return diagnostics


def evaluate_expression_ast(expression: Any, context: Dict[str, Any]) -> Any:
    """Evaluate only the typed AST; no Python/SQL expression is interpreted."""
    diagnostics = validate_expression_ast(expression)
    if diagnostics:
        raise ValueError(diagnostics[0]["message"])
    if expression in (None, {}, []):
        return True
    op = str(expression.get("op") or "").lower()
    if op == "literal":
        return expression.get("value")
    if op == "ref":
        value: Any = context
        path = str(expression.get("path") or expression.get("ref") or "").split(".")
        for part in path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value
    if op in {"and", "or"}:
        values = [evaluate_expression_ast(item, context) for item in expression.get("args", [])]
        return all(values) if op == "and" else any(values)
    if op == "not":
        return not evaluate_expression_ast(expression["args"][0], context)
    if op == "is_null":
        return evaluate_expression_ast(expression.get("value"), context) is None
    if op in {"eq", "ne", "gt", "gte", "lt", "lte"}:
        left = evaluate_expression_ast(expression.get("left"), context)
        right = evaluate_expression_ast(expression.get("right"), context)
        return {"eq": left == right, "ne": left != right, "gt": left > right,
                "gte": left >= right, "lt": left < right, "lte": left <= right}[op]
    if op in {"in", "contains"}:
        left = evaluate_expression_ast(expression.get("left"), context)
        right = evaluate_expression_ast(expression.get("right"), context)
        return left in right if op == "in" else right in left
    if op in {"starts_with", "ends_with"}:
        left = str(evaluate_expression_ast(expression.get("left"), context) or "")
        right = str(evaluate_expression_ast(expression.get("right"), context) or "")
        return left.startswith(right) if op == "starts_with" else left.endswith(right)
    if op in {"add", "sub", "mul", "div"}:
        left = evaluate_expression_ast(expression.get("left"), context)
        right = evaluate_expression_ast(expression.get("right"), context)
        if op == "add":
            return left + right
        if op == "sub":
            return left - right
        if op == "mul":
            return left * right
        return left / right
    raise ValueError(f"unsupported expression operator: {op}")


def _reachable(start: str, adjacency: Dict[str, List[str]]) -> Set[str]:
    seen: Set[str] = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(adjacency.get(node, []))
    return seen


def _cycle_nodes(adjacency: Dict[str, List[str]]) -> Set[str]:
    visiting: Set[str] = set()
    visited: Set[str] = set()
    cycles: Set[str] = set()

    def walk(node: str, path: List[str]) -> None:
        if node in visiting:
            if node in path:
                cycles.update(path[path.index(node):])
            return
        if node in visited:
            return
        visiting.add(node)
        for target in adjacency.get(node, []):
            walk(target, path + [node])
        visiting.remove(node)
        visited.add(node)

    for node in adjacency:
        walk(node, [])
    return cycles


def _risk(nodes: Iterable[Dict[str, Any]], edges: Iterable[Dict[str, Any]], diagnostics: List[Dict[str, Any]]) -> str:
    level = "LOW"
    for node in nodes:
        if node["side_effect_class"] == "NON_IDEMPOTENT":
            level = "HIGH"
        elif node["side_effect_class"] == "IDEMPOTENT_EXTERNAL" and RISK_ORDER[level] < RISK_ORDER["MEDIUM"]:
            level = "MEDIUM"
        if node.get("resource_scope") and RISK_ORDER[level] < RISK_ORDER["MEDIUM"]:
            level = "MEDIUM"
    for edge in edges:
        if edge["decision_type"] in {"MODEL", "HUMAN"} and RISK_ORDER[level] < RISK_ORDER["MEDIUM"]:
            level = "MEDIUM"
    if any(item["code"].startswith("PERMISSION") or item["code"].startswith("UNSAFE") for item in diagnostics):
        level = "HIGH"
    return level


def _schema_properties(schema: Any) -> Dict[str, Any]:
    return dict((schema or {}).get("properties") or {}) if isinstance(schema, dict) else {}


def _validate_schema_boundary(source: Dict[str, Any], target: Dict[str, Any], edge_id: str) -> List[Dict[str, Any]]:
    """Check the small JSON-schema contract without pretending to be a full validator."""
    source_props = _schema_properties(source.get("output_schema"))
    target_schema = target.get("input_schema") or {}
    required = set(target_schema.get("required") or []) if isinstance(target_schema, dict) else set()
    missing = sorted(required - set(source_props)) if source_props else []
    if missing:
        return [_diag(
            "SCHEMA_INPUT_UNSATISFIED",
            f"edge {edge_id} cannot satisfy target input fields: {', '.join(missing)}",
            edge_id=edge_id, fields=missing,
        )]
    diagnostics: List[Dict[str, Any]] = []
    for name, target_prop in _schema_properties(target_schema).items():
        source_prop = source_props.get(name)
        if not source_prop or not isinstance(target_prop, dict) or not isinstance(source_prop, dict):
            continue
        if target_prop.get("type") and source_prop.get("type") and target_prop["type"] != source_prop["type"]:
            diagnostics.append(_diag(
                "SCHEMA_TYPE_MISMATCH",
                f"edge {edge_id} field {name} changes type {source_prop['type']} -> {target_prop['type']}",
                edge_id=edge_id, field=name,
            ))
    return diagnostics


def compile_definition(definition: Dict[str, Any], *, adapter: Optional[Dict[str, Any]] = None,
                       registry: Optional[Any] = None) -> Dict[str, Any]:
    """Compile a logical definition without making database or network calls."""
    diagnostics: List[Dict[str, Any]] = []
    type_registry = _normalize_registry(registry if registry is not None else (adapter or {}).get("registry"))
    resolved_dependencies, dependency_diagnostics = _dependency_manifests(definition, type_registry)
    diagnostics.extend(dependency_diagnostics)
    nodes = [_normalize_node(node) for node in definition.get("nodes", [])]
    edges = [_normalize_edge(edge) for edge in definition.get("edges", [])]
    keys = [_node_key(node) for node in nodes]
    if not nodes:
        diagnostics.append(_diag("GRAPH_EMPTY", "graph version must contain at least one node"))
    if any(not key for key in keys):
        diagnostics.append(_diag("NODE_KEY_MISSING", "every node requires a node_key"))
    if len(keys) != len(set(keys)):
        diagnostics.append(_diag("NODE_KEY_DUPLICATE", "node_key values must be unique"))
    node_map = {key: node for key, node in zip(keys, nodes) if key}
    starts = [node["node_key"] for node in nodes if node["node_type"] == "START" or node.get("config", {}).get("entry") is True]
    ends = [node["node_key"] for node in nodes if node["node_type"] == "END" or node.get("config", {}).get("exit") is True]
    if len(starts) != 1:
        diagnostics.append(_diag("ENTRY_COUNT", "graph must have exactly one entry node", count=len(starts)))
    if not ends:
        diagnostics.append(_diag("EXIT_MISSING", "graph must have at least one exit node"))
    adjacency: Dict[str, List[str]] = defaultdict(list)
    incoming: Dict[str, int] = defaultdict(int)
    incoming_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    edge_ids: Set[str] = set()
    for edge in edges:
        source = edge["source_node_key"]
        target = edge["target_node_key"]
        if edge["edge_id"] in edge_ids:
            diagnostics.append(_diag("EDGE_ID_DUPLICATE", f"duplicate edge id: {edge['edge_id']}"))
        edge_ids.add(edge["edge_id"])
        if not edge["edge_id"]:
            diagnostics.append(_diag("EDGE_ID_MISSING", "every edge requires an edge_id"))
        if source not in node_map or target not in node_map:
            diagnostics.append(_diag("EDGE_NODE_MISSING", "edge references an unknown node", edge_id=edge["edge_id"]))
            continue
        adjacency[source].append(target)
        incoming[target] += 1
        incoming_edges[target].append(edge)
        if edge["edge_kind"] not in EDGE_KINDS:
            diagnostics.append(_diag("EDGE_KIND_UNAVAILABLE", f"edge kind unavailable: {edge['edge_kind']}", edge_id=edge["edge_id"]))
        decision_key = _type_key("DECISION", edge["decision_type"], "1.0")
        if decision_key not in type_registry:
            diagnostics.append(_diag("DECISION_TYPE_UNAVAILABLE", f"decision type unavailable: {edge['decision_type']}", edge_id=edge["edge_id"]))
        if edge["decision_type"] == "EXPRESSION":
            diagnostics.extend(validate_expression_ast(edge["condition"], f"edge.{edge['edge_id']}.condition"))
        if edge["config"].get("timeout_seconds") is not None:
            try:
                if float(edge["config"]["timeout_seconds"]) <= 0:
                    diagnostics.append(_diag("TIMEOUT_INVALID", "timeout_seconds must be positive", edge_id=edge["edge_id"]))
            except (TypeError, ValueError):
                diagnostics.append(_diag("TIMEOUT_INVALID", "timeout_seconds must be numeric", edge_id=edge["edge_id"]))
    for node in nodes:
        node_key = _type_key("NODE", node["node_type"], node["type_version"])
        if node_key not in type_registry:
            diagnostics.append(_diag("NODE_TYPE_UNAVAILABLE", f"node type unavailable: {node['node_type']}", node_key=node["node_key"]))
        if node["side_effect_class"] not in NODE_SIDE_EFFECT_CLASSES:
            diagnostics.append(_diag("SIDE_EFFECT_CLASS_INVALID", f"unsupported side effect class: {node['side_effect_class']}", node_key=node["node_key"]))
        forbidden = _contains_forbidden(node.get("config"))
        if forbidden:
            diagnostics.append(_diag("UNSAFE_NODE_CONFIG", f"node config contains forbidden capability: {forbidden}", node_key=node["node_key"]))
        for budget_key, budget_value in (node.get("budget") or {}).items():
            if budget_key in HARD_BUDGET_KEYS and (isinstance(budget_value, bool) or not isinstance(budget_value, (int, float)) or not math.isfinite(float(budget_value)) or budget_value <= 0):
                diagnostics.append(_diag("BUDGET_INVALID", f"{budget_key} must be a positive number", node_key=node["node_key"]))
        retry = node.get("config", {}).get("retry_policy") or {}
        max_attempts = retry.get("max_attempts", 1)
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, (int, float)) or int(max_attempts) < 1:
            diagnostics.append(_diag("RETRY_POLICY_INVALID", "retry_policy.max_attempts must be a positive integer", node_key=node["node_key"]))
        if node["side_effect_class"] == "NON_IDEMPOTENT" and int(max_attempts or 1) > 1:
            if not retry.get("compensation_edge_id") and not retry.get("confirmation_required"):
                diagnostics.append(_diag(
                    "NON_IDEMPOTENT_RETRY_UNSAFE",
                    "non-idempotent nodes require compensation or outcome confirmation before retry",
                    node_key=node["node_key"],
                ))
    for target, target_edges in incoming_edges.items():
        # A self-loop is a cycle transition, not a second fan-in branch.  It
        # must not force a Join key on an otherwise valid bounded cycle.
        join_edges = [edge for edge in target_edges if edge["source_node_key"] != target]
        if len(join_edges) <= 1:
            continue
        join_keys = {str(edge.get("join_key") or edge.get("config", {}).get("join_key") or "") for edge in join_edges}
        if "" in join_keys or len(join_keys) != 1:
            diagnostics.append(_diag(
                "JOIN_KEY_MISSING", f"fan-in target {target} requires one shared join_key", node_key=target,
            ))
            continue
        strategies = {str(edge.get("config", {}).get("join_strategy") or "ALL").upper() for edge in join_edges}
        if not strategies <= JOIN_STRATEGIES:
            diagnostics.append(_diag("JOIN_STRATEGY_UNAVAILABLE", f"unsupported join strategy for {target}", node_key=target))
        if len(strategies) > 1:
            diagnostics.append(_diag("JOIN_STRATEGY_CONFLICT", f"fan-in target {target} has conflicting join strategies", node_key=target))
        reducers = {str(edge.get("config", {}).get("reducer") or "REPLACE").upper() for edge in join_edges}
        if len(reducers) > 1:
            diagnostics.append(_diag("REDUCER_CONFLICT", f"fan-in target {target} has conflicting reducers", node_key=target))
        for reducer in reducers:
            if _type_key("REDUCER", reducer, "1.0") not in type_registry:
                diagnostics.append(_diag("REDUCER_UNAVAILABLE", f"reducer unavailable: {reducer}", node_key=target))
        strategy = next(iter(strategies), "ALL")
        required_count = next((edge.get("config", {}).get("required_count") for edge in join_edges if edge.get("config", {}).get("required_count") is not None), None)
        if required_count is not None and (isinstance(required_count, bool) or not isinstance(required_count, int) or required_count < 1 or required_count > len(join_edges)):
            diagnostics.append(_diag("JOIN_REQUIRED_COUNT_INVALID", f"join required_count is outside 1..{len(join_edges)}", node_key=target))
        if strategy in {"ALL", "FIRST_SUCCESS"} and required_count is not None and required_count != len(join_edges):
            diagnostics.append(_diag("JOIN_REQUIRED_COUNT_CONFLICT", f"{strategy} join requires all incoming branches", node_key=target))
    for edge in edges:
        source_node = node_map.get(edge["source_node_key"])
        target_node = node_map.get(edge["target_node_key"])
        if source_node and target_node:
            diagnostics.extend(_validate_schema_boundary(source_node, target_node, edge["edge_id"]))
    if starts:
        reachable = _reachable(starts[0], adjacency)
        for key in node_map:
            if key not in reachable:
                diagnostics.append(_diag("NODE_UNREACHABLE", f"node is unreachable from entry: {key}", node_key=key))
    for key in node_map:
        if key not in ends and not adjacency.get(key):
            diagnostics.append(_diag("NODE_DEAD_END", f"non-terminal node has no outgoing edge: {key}", node_key=key))
    cycles = _cycle_nodes(adjacency)
    graph_budget = definition.get("budget") or {}
    for budget_key, budget_value in graph_budget.items():
        if budget_key in HARD_BUDGET_KEYS and (isinstance(budget_value, bool) or not isinstance(budget_value, (int, float)) or not math.isfinite(float(budget_value)) or budget_value <= 0):
            diagnostics.append(_diag("BUDGET_INVALID", f"{budget_key} must be a positive number", path=f"budget.{budget_key}"))
    for key in sorted(cycles):
        node_budget = node_map.get(key, {}).get("budget") or {}
        if not any(node_budget.get(name) is not None or graph_budget.get(name) is not None for name in (
            "max_iterations", "max_calls", "max_tokens", "max_duration_seconds", "max_cost",
        )):
            diagnostics.append(_diag("CYCLE_UNBOUNDED", f"cycle requires a hard budget: {key}", node_key=key))
    if definition.get("strict_schema") is True:
        for edge in edges:
            source_node = node_map.get(edge["source_node_key"])
            target_node = node_map.get(edge["target_node_key"])
            if source_node and target_node:
                required = set((target_node.get("input_schema") or {}).get("required") or [])
                source_props = _schema_properties(source_node.get("output_schema"))
                missing = sorted(required - set(source_props))
                if missing:
                    diagnostics.append(_diag("SCHEMA_INPUT_UNSATISFIED", f"edge {edge['edge_id']} cannot satisfy target input fields: {', '.join(missing)}", edge_id=edge["edge_id"], fields=missing))
    for node in nodes:
        executor = (node.get("config") or {}).get("executor")
        if executor:
            executor_name = str(executor.get("name") if isinstance(executor, dict) else executor)
            executor_version = str(executor.get("version", "1.0") if isinstance(executor, dict) else "1.0")
            if _type_key("EXECUTOR", executor_name, executor_version) not in type_registry:
                diagnostics.append(_diag("EXECUTOR_UNAVAILABLE", f"executor unavailable: {executor_name}/{executor_version}", node_key=node["node_key"]))
        if (node.get("config") or {}).get("failure_path_required") is True:
            outgoing = [edge for edge in edges if edge["source_node_key"] == node["node_key"]]
            if not any(edge["edge_kind"] in {"ERROR", "TIMEOUT", "COMPENSATION", "FALLBACK"} for edge in outgoing):
                diagnostics.append(_diag("FAILURE_PATH_MISSING", "node requires an explicit failure path", node_key=node["node_key"]))
    normalized_definition = {
        "schema_version": definition.get("schema_version") or GRAPH_SCHEMA_VERSION,
        "graph_version_id": definition.get("graph_version_id"),
        "graph_id": definition.get("graph_id"),
        "input_schema": definition.get("input_schema") or {},
        "output_schema": definition.get("output_schema") or {},
        "budget": graph_budget,
        "type_dependencies": resolved_dependencies,
        "nodes": sorted(nodes, key=lambda item: item["node_key"]),
        "edges": sorted(edges, key=lambda item: (item["source_node_key"], item["order_index"], item["edge_id"])),
    }
    definition_digest = digest(normalized_definition)
    risk_level = _risk(nodes, edges, diagnostics)
    plan = {
        "plan_schema": "graph-execution-plan/1",
        "compiler_version": COMPILER_VERSION,
        "definition_digest": definition_digest,
        "graph_version_id": definition.get("graph_version_id"),
        "nodes": normalized_definition["nodes"],
        "edges": normalized_definition["edges"],
        "entry_node": starts[0] if len(starts) == 1 else None,
        "exit_nodes": sorted(ends),
        "cycle_nodes": sorted(cycles),
        "incoming_edges": {
            key: [edge["edge_id"] for edge in incoming_edges.get(key, [])]
            for key in sorted(node_map)
        },
        "join_specs": {
            key: {
                "join_key": next(iter({str(edge.get("join_key") or edge.get("config", {}).get("join_key")) for edge in incoming_edges.get(key, []) if edge["source_node_key"] != key}), None),
                "strategy": next(iter({str(edge.get("config", {}).get("join_strategy") or "ALL").upper() for edge in incoming_edges.get(key, []) if edge["source_node_key"] != key}), "ALL"),
                "expected_count": len([edge for edge in incoming_edges.get(key, []) if edge["source_node_key"] != key]),
                "reducer": next(iter({str(edge.get("config", {}).get("reducer") or "REPLACE").upper() for edge in incoming_edges.get(key, []) if edge["source_node_key"] != key}), "REPLACE"),
            }
            for key in sorted(node_map) if len([edge for edge in incoming_edges.get(key, []) if edge["source_node_key"] != key]) > 1
        },
        "node_index": {node["node_key"]: node for node in normalized_definition["nodes"]},
        "budget": graph_budget,
        "type_dependencies": resolved_dependencies,
        "adapter": adapter or {},
        "risk_level": risk_level,
    }
    logical_plan = dict(plan)
    logical_plan.pop("adapter", None)
    plan_digest = digest(logical_plan)
    return {
        "valid": not diagnostics,
        "definition": normalized_definition,
        "plan": plan,
        "diagnostics": diagnostics,
        "warnings": [],
        "risk_level": risk_level,
        "definition_digest": definition_digest,
        "plan_digest": plan_digest,
    }


def compile_version(version_id: str, *, persist: bool = True) -> Dict[str, Any]:
    from . import graph_definition_api as definitions
    version = definitions.get_version(version_id, include_topology=True)
    if not version:
        raise ValueError(f"Graph Version {version_id} not found")
    if str(version.get("status") or "").upper() not in {"DRAFT", "VALIDATED"}:
        raise ValueError(f"Graph Version {version_id} cannot be compiled from status {version.get('status')}")
    registered = definitions.list_types(limit=500)
    result = compile_definition({
        "graph_id": version.get("graph_id"), "graph_version_id": version_id,
        "schema_version": version.get("schema_version"),
        "input_schema": version.get("input_schema") or {}, "output_schema": version.get("output_schema") or {},
        "budget": version.get("budget") or {}, "nodes": version.get("nodes") or [], "edges": version.get("edges") or [],
    }, adapter={"dialect": "portable"}, registry=registered)
    if persist and result["valid"]:
        definitions.set_validation_result(version_id, result["definition_digest"], {
            "errors": [], "warnings": result["warnings"], "compiler_version": COMPILER_VERSION,
        }, result["risk_level"])
        result["plan_id"] = definitions.set_compiled_plan(
            version_id, COMPILER_VERSION, result["definition_digest"], result["plan"],
            result["plan_digest"], {"errors": [], "warnings": result["warnings"]}, result["risk_level"],
        )
    return result


def compile_and_publish(version_id: str, actor_id: str, reason: str) -> Dict[str, Any]:
    from . import graph_definition_api as definitions

    result = compile_version(version_id, persist=True)
    if not result["valid"]:
        return result
    definitions.transition_version(version_id, "PUBLISHED", actor_id, reason)
    result["published"] = True
    return result
