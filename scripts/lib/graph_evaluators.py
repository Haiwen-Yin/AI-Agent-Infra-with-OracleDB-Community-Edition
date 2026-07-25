"""Versioned, side-effect-free evaluator contracts for Graph Engineering.

The existing Loop engine may still execute an evaluator through a durable job
or an external service.  This module owns the common registration shape and
normalizes an already-produced observation; it never runs a shell command,
calls an LLM, or reads the database.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


EVALUATOR_VERSION = "1.0"
EVALUATOR_LEVELS = frozenset({"NODE", "EDGE", "TRAJECTORY", "OUTCOME", "RELIABILITY"})
EVALUATOR_TYPES = frozenset({
    "MANUAL", "TEST", "DIFF", "LLM_JUDGE", "SPEC_VALIDATION", "AGGREGATE",
})


def builtin_evaluator_manifests() -> List[Dict[str, Any]]:
    """Return the stable registration manifests for the six Loop evaluators."""
    return [
        {"name": "MANUAL", "version": EVALUATOR_VERSION, "levels": ["OUTCOME"], "deterministic": False, "legacy_types": ["MANUAL"]},
        {"name": "TEST", "version": EVALUATOR_VERSION, "levels": ["NODE", "OUTCOME"], "deterministic": True, "legacy_types": ["TEST"]},
        {"name": "DIFF", "version": EVALUATOR_VERSION, "levels": ["NODE", "TRAJECTORY"], "deterministic": True, "legacy_types": ["DIFF"]},
        {"name": "LLM_JUDGE", "version": EVALUATOR_VERSION, "levels": ["OUTCOME"], "deterministic": False, "legacy_types": ["LLM_JUDGE"]},
        {"name": "SPEC_VALIDATION", "version": EVALUATOR_VERSION, "levels": ["OUTCOME", "RELIABILITY"], "deterministic": True, "legacy_types": ["SPEC_VALIDATION"]},
        {"name": "AGGREGATE", "version": EVALUATOR_VERSION, "levels": ["TRAJECTORY", "OUTCOME"], "deterministic": True, "legacy_types": ["AGGREGATE"]},
    ]


def validate_manifest(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Validate the portable evaluator registry subset."""
    errors: List[Dict[str, Any]] = []
    if not isinstance(manifest, dict):
        return [{"code": "EVALUATOR_MANIFEST_OBJECT_REQUIRED"}]
    name = str(manifest.get("name") or "").upper()
    version = str(manifest.get("version") or "")
    levels = manifest.get("levels")
    if not name:
        errors.append({"code": "EVALUATOR_NAME_REQUIRED"})
    if not version:
        errors.append({"code": "EVALUATOR_VERSION_REQUIRED"})
    if not isinstance(levels, list) or not levels:
        errors.append({"code": "EVALUATOR_LEVELS_REQUIRED"})
    elif not {str(level).upper() for level in levels} <= EVALUATOR_LEVELS:
        errors.append({"code": "EVALUATOR_LEVEL_INVALID"})
    if not isinstance(manifest.get("deterministic"), bool):
        errors.append({"code": "EVALUATOR_DETERMINISM_REQUIRED"})
    return errors


def normalize_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize legacy Loop config and reject unregistered evaluator types."""
    config = dict(config or {})
    name = str(config.get("type_name") or config.get("evaluator") or config.get("eval_type") or "MANUAL").upper()
    if name not in EVALUATOR_TYPES:
        raise ValueError(f"unknown Graph evaluator: {name}")
    level = str(config.get("level") or "OUTCOME").upper()
    if level not in EVALUATOR_LEVELS:
        raise ValueError(f"unknown Graph evaluator level: {level}")
    return {
        "type_name": name,
        "type_version": str(config.get("type_version") or EVALUATOR_VERSION),
        "level": level,
        "parameters": {key: value for key, value in config.items()
                        if key not in {"type_name", "evaluator", "eval_type", "type_version", "level"}},
    }


def _result(contract: Dict[str, Any], passed: bool, *, pending: bool = False,
            route_decision: str = "CONTINUE", details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "evaluator": contract["type_name"],
        "evaluator_version": contract["type_version"],
        "level": contract["level"],
        "passed": bool(passed),
        "pending": bool(pending),
        "route_decision": route_decision,
        "details": details or {},
    }


def evaluate_observation(config: Optional[Dict[str, Any]], observation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Evaluate a completed observation using only declared data.

    External work such as a test process or an LLM call must be performed by a
    governed Node Executor.  The executor feeds its sanitized result here.
    """
    contract = normalize_config(config)
    observation = dict(observation or {})
    name = contract["type_name"]
    parameters = contract["parameters"]
    if name == "MANUAL":
        return _result(contract, False, pending=True, route_decision="REVIEW", details={"status": "AWAITING_REVIEW"})
    if name == "TEST":
        if "exit_code" not in observation:
            return _result(contract, False, pending=True, details={"status": "AWAITING_RESULT"})
        expected = int(parameters.get("success_exit_code", 0))
        passed = observation.get("exit_code") == expected
        return _result(contract, passed, route_decision="STOP" if passed else "CONTINUE",
                       details={"exit_code": observation.get("exit_code"), "expected_exit_code": expected})
    if name == "DIFF":
        changed = observation.get("changed_files") or []
        forbidden = set(map(str, parameters.get("forbidden_files") or []))
        violations = sorted(forbidden.intersection(map(str, changed)))
        maximum = parameters.get("max_changed_files")
        over_limit = isinstance(maximum, int) and len(changed) > maximum
        passed = not violations and not over_limit
        return _result(contract, passed, route_decision="STOP" if passed else "CONTINUE",
                       details={"changed_files": len(changed), "violations": violations, "over_limit": over_limit})
    if name == "LLM_JUDGE":
        if not isinstance(observation.get("score"), (int, float)):
            return _result(contract, False, pending=True, details={"status": "AWAITING_RESULT"})
        minimum = float(parameters.get("min_score", 7))
        score = float(observation["score"])
        passed = score >= minimum
        return _result(contract, passed, route_decision="STOP" if passed else "CONTINUE",
                       details={"score": score, "min_score": minimum})
    if name == "SPEC_VALIDATION":
        criteria = observation.get("criteria") or []
        results = [item for item in criteria if isinstance(item, dict)]
        if not results:
            return _result(contract, False, pending=True, details={"status": "AWAITING_CRITERIA"})
        passed = all(item.get("passed") is True for item in results)
        return _result(contract, passed, route_decision="STOP" if passed else "CONTINUE",
                       details={"total": len(results), "passed_count": sum(item.get("passed") is True for item in results)})
    children = observation.get("children") or []
    terminal = [item for item in children if isinstance(item, dict) and item.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}]
    if not terminal or len(terminal) != len(children):
        return _result(contract, False, pending=True, details={"status": "AWAITING_CHILDREN", "total": len(children), "terminal": len(terminal)})
    passed = bool(children) and all(item.get("status") == "SUCCEEDED" for item in terminal)
    return _result(contract, passed, route_decision="STOP" if passed else "CONTINUE",
                   details={"total": len(terminal), "failed": sum(item.get("status") != "SUCCEEDED" for item in terminal)})


def compute_metrics(*, transitions: Optional[Iterable[Dict[str, Any]]] = None,
                    attempts: Optional[Iterable[Dict[str, Any]]] = None,
                    interventions: Optional[Iterable[Dict[str, Any]]] = None,
                    budget: Optional[Dict[str, Any]] = None,
                    usage: Optional[Dict[str, Any]] = None,
                    planned_nodes: Optional[int] = None) -> Dict[str, Any]:
    """Compute bounded, auditable metrics from already persisted summaries."""
    transitions = list(transitions or [])
    attempts = list(attempts or [])
    interventions = list(interventions or [])
    usage = dict(usage or {})
    normalized_attempts = [dict(item) for item in attempts]
    successful_attempts = sum(str(item.get("status") or "").upper() == "SUCCEEDED" for item in normalized_attempts)
    node_runs = {str(item.get("node_run_id")) for item in attempts if item.get("node_run_id")}
    retries = max(0, len(attempts) - len(node_runs))
    committed = sum(str(item.get("status") or "").upper() == "COMMITTED" for item in transitions)
    efficiency = None if not planned_nodes else round(committed / max(1, int(planned_nodes)), 6)
    reliability = None if not attempts else round(successful_attempts / len(attempts), 6)
    failures = sum(str(item.get("status") or "").upper() in {"FAILED", "CANCELLED", "REVIEW_REQUIRED"}
                   or str(item.get("error_code") or "").upper() in {"TIMEOUT", "DEADLINE_EXPIRED"}
                   for item in normalized_attempts)
    timeout_count = sum(str(item.get("status") or "").upper() in {"TIMEOUT", "TIMED_OUT"}
                        or str(item.get("error_code") or "").upper() in {"TIMEOUT", "DEADLINE_EXPIRED"}
                        for item in normalized_attempts)
    route_samples = [item for item in transitions if any(
        key in item for key in ("route_expected", "expected", "route_correct", "correct")
    )]
    route_correct = sum(bool(item.get("route_correct", item.get("correct", item.get("route_expected", item.get("expected")))))
                       for item in route_samples)
    route_quality = None if not route_samples else round(route_correct / len(route_samples), 6)
    token_usage = usage.get("tokens", usage.get("token_count"))
    cost_usage = usage.get("cost", usage.get("estimated_cost"))
    durations = [float(item["duration_ms"]) for item in normalized_attempts
                 if isinstance(item.get("duration_ms"), (int, float)) and item["duration_ms"] >= 0]
    latency = {
        "count": len(durations),
        "avg_ms": round(sum(durations) / len(durations), 3) if durations else None,
        "max_ms": max(durations) if durations else None,
    }
    utilization = {}
    for key, limit in (budget or {}).items():
        if not str(key).startswith("max_") or not isinstance(limit, (int, float)) or limit <= 0:
            continue
        metric = str(key)[4:]
        if isinstance(usage.get(metric), (int, float)):
            utilization[metric] = round(usage[metric] / limit, 6)
    return {
        "schema": "graph-evaluation-metrics/1",
        "path_efficiency": efficiency,
        "committed_transitions": committed,
        "retry_count": retries,
        "reliability": reliability,
        "route_quality": route_quality,
        "failure_count": failures,
        "timeout_count": timeout_count,
        "token_usage": token_usage if isinstance(token_usage, (int, float)) else None,
        "cost_usage": cost_usage if isinstance(cost_usage, (int, float)) else None,
        "latency": latency,
        "intervention_count": len(interventions),
        "budget_utilization": utilization,
        "evidence": {
            "attempts": len(normalized_attempts), "node_runs": len(node_runs),
            "transitions": len(transitions), "route_samples": len(route_samples),
            "planned_nodes": int(planned_nodes) if isinstance(planned_nodes, int) and planned_nodes > 0 else None,
        },
    }
