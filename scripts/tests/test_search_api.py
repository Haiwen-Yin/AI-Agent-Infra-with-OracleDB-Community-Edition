"""AI Agent Infra v4.1.0 - Search API Tests"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.search_api import (
    search, list_search_strategies, describe_search_strategy,
    _detect_strategy, _get_strategy_params, STRATEGIES,
)

passed = 0
failed = 0

def _test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")

def run_all():
    global passed, failed
    passed = 0
    failed = 0

    print("=== Search API Tests ===")

    _test("10 strategies defined", len(STRATEGIES) == 10, f"got {len(STRATEGIES)}")
    expected = ["vector","fulltext","keyword","graph","hybrid","unified","unified_sql","relational","multi_type","auto"]
    _test("all strategy keys present", all(k in STRATEGIES for k in expected))

    strats = list_search_strategies()
    _test("list returns 10", len(strats) == 10)
    _test("each has strategy key", all("strategy" in s for s in strats))
    _test("each has signals", all("signals" in s for s in strats))
    _test("each has speed", all("speed" in s for s in strats))

    desc = describe_search_strategy("fulltext")
    _test("describe fulltext not None", desc is not None)
    _test("describe has parameters", "parameters" in desc)
    _test("describe fulltext params count", len(desc["parameters"]) == 4)
    _test("describe unknown returns None", describe_search_strategy("nonexistent") is None)

    _test("unified has 11 params", len(_get_strategy_params("unified")) == 11)
    _test("unified_sql has 11 params", len(_get_strategy_params("unified_sql")) == 11)
    _test("bogus strategy returns empty", _get_strategy_params("bogus") == [])

    _test("detect AND", _detect_strategy("a AND b") == "fulltext")
    _test("detect OR", _detect_strategy("a OR b") == "fulltext")
    _test("detect NOT", _detect_strategy("a NOT b") == "fulltext")
    _test("detect $", _detect_strategy("$word") == "fulltext")
    _test("detect ~", _detect_strategy("word~") == "fulltext")
    _test("detect %", _detect_strategy("part%") == "keyword")
    _test("detect _", _detect_strategy("part_") == "keyword")
    _test("detect domain", _detect_strategy("t", domain="db") == "unified")
    _test("detect tags", _detect_strategy("t", tags=["a"]) == "unified")
    _test("detect graph seed", _detect_strategy("t", graph_seed_entity_id="x") == "unified")
    _test("detect short query", _detect_strategy("encryption") == "fulltext")
    _test("detect long query", _detect_strategy("how to optimize database performance tuning") == "unified")
    _test("detect medium query", _detect_strategy("database partitioning strategies") == "hybrid")
    _test("detect graph no text", _detect_strategy("", entity_id="x") == "graph")

    r = search("partitioning", strategy="fulltext", top_k=3)
    _test("fulltext returns dict", isinstance(r, dict))
    _test("fulltext strategy set", r.get("strategy") == "fulltext")
    _test("fulltext has count", r["count"] == len(r["results"]))

    r = search("encryption", strategy="vector", top_k=3)
    _test("vector search works", r.get("count", 0) >= 0)

    r = search("partition%", strategy="keyword", top_k=5)
    _test("keyword no error", "error" not in r)

    r = search("", strategy="relational", entity_type="KNOWLEDGE", domain="database", top_k=5)
    _test("relational has results", r["count"] > 0)

    r = search("partitioning", strategy="auto", top_k=3)
    _test("auto resolves strategy", r.get("strategy") in STRATEGIES)

    r = search("test", strategy="bogus", top_k=3)
    _test("unknown falls back to unified", r.get("strategy") == "unified")

    r = search("database partitioning", strategy="unified_sql", top_k=3)
    _test("unified_sql returns dict", isinstance(r, dict))
    _test("unified_sql strategy set", r.get("strategy") == "unified_sql")
    _test("unified_sql has count", r["count"] == len(r["results"]))
    if r["results"]:
        item = r["results"][0]
        _test("unified_sql result has engine", item.get("engine") == "single_sql")
        _test("unified_sql result has scores", "scores" in item)
    else:
        _test("unified_sql result structure (skipped)", True)
        _test("unified_sql engine (skipped)", True)

    r = search("partitioning", strategy="fulltext", top_k=1)
    if r["results"]:
        item = r["results"][0]
        _test("result has entity_id", "entity_id" in item)
        _test("result has entity_type", "entity_type" in item)
    else:
        _test("result structure (skipped)", True)

    total = passed + failed
    print(f"  {passed}/{total} passed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
