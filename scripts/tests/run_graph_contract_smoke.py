"""Run database-independent Graph contract checks without pytest."""

from __future__ import annotations

import json
import math

from lib.graph_compiler import ExpressionContractError, evaluate_expression_ast, validate_expression_ast
from lib.graph_contracts import completion_request_digest
from lib.graph_event_contract import validate_event
from lib.graph_executor import effect_idempotency_key, side_effect_retry_decision


def _assert_expression_diagnostics() -> None:
    cases = [
        ({"op": "eq"}, "EXPRESSION_OPERAND_MISSING"),
        ({"op": "eq", "left": {}, "right": {"op": "literal", "value": 1}}, "EXPRESSION_CHILD"),
        ({"op": "in", "left": {"op": "literal", "value": "READY"},
          "right": {"op": "literal", "value": None}}, "EXPRESSION_CONTAINER_INVALID"),
        ({"op": "eq", "left": {"op": "literal", "value": 1},
          "right": {"op": "literal", "value": "1"}}, "EXPRESSION_TYPE_MISMATCH"),
        ({"op": "div", "left": {"op": "literal", "value": 1},
          "right": {"op": "literal", "value": 0}}, "EXPRESSION_DIVISION_BY_ZERO"),
    ]
    for expression, expected_code in cases:
        diagnostics = validate_expression_ast(expression)
        assert any(item["code"] == expected_code for item in diagnostics), diagnostics

    try:
        evaluate_expression_ast(
            {"op": "in", "left": {"op": "ref", "path": "state.value"},
             "right": {"op": "ref", "path": "state.container"}},
            {"state": {"value": "READY", "container": None}},
        )
    except ExpressionContractError as exc:
        assert exc.diagnostic["code"] == "EXPRESSION_CONTAINER_INVALID"
    else:
        raise AssertionError("native container TypeError was not wrapped")


def _assert_effect_and_event_boundaries() -> None:
    key = effect_idempotency_key("RUN_SMOKE", "NODE_SMOKE", "IDEMPOTENT_EXTERNAL")
    assert key == effect_idempotency_key("RUN_SMOKE", "NODE_SMOKE", "IDEMPOTENT_EXTERNAL")
    assert key != effect_idempotency_key("RUN_SMOKE", "NODE_OTHER", "IDEMPOTENT_EXTERNAL")
    assert effect_idempotency_key("RUN:SMOKE", "NODE", "IDEMPOTENT_EXTERNAL") != effect_idempotency_key(
        "RUN", "SMOKE:NODE", "IDEMPOTENT_EXTERNAL",
    )
    assert effect_idempotency_key("RUN_SMOKE", "NODE_SMOKE", "NON_IDEMPOTENT") is None
    retry = side_effect_retry_decision("IDEMPOTENT_EXTERNAL", "OUTCOME_UNKNOWN", 1, 2)
    assert retry["retry"] is True and retry["uncertain_outcome"] is True
    review = side_effect_retry_decision("NON_IDEMPOTENT", "OUTCOME_UNKNOWN", 1, 2)
    assert review["status"] == "REVIEW_REQUIRED" and review["retry"] is False
    event_errors = validate_event(
        "source-smoke", "GRAPH_READY", "1", "evt-smoke", {"value": math.nan},
    )
    assert any(item["code"] == "EVENT_PAYLOAD_NOT_JSON" for item in event_errors)


def run() -> dict[str, object]:
    _assert_expression_diagnostics()
    _assert_effect_and_event_boundaries()
    first = completion_request_digest({"b": 2, "a": 1}, {"tokens": 3})
    second = completion_request_digest({"a": 1, "b": 2}, {"tokens": 3})
    different = completion_request_digest({"a": 1, "b": 2}, {"tokens": 4})
    assert first == second
    assert first != different
    return {"passed": True, "checks": [
        "expression-contract", "completion-digest", "effect-retry", "event-json",
    ]}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True))
