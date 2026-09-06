import pytest

try:
    from shared.lib import model_usage_api as api
except ModuleNotFoundError:
    from lib import model_usage_api as api


def test_usage_reads_nested_details_without_adding_to_total():
    usage = api._usage({"usage": {
        "prompt_tokens": 100, "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 40},
        "completion_tokens_details": {"reasoning_tokens": 20},
    }})
    assert usage == dict(prompt_tokens=100, completion_tokens=50, cached_tokens=40,
                         reasoning_tokens=20, total_tokens=150)


def pricing(monkeypatch, **overrides):
    row = dict(input_per_million=2, output_per_million=4,
               cache_per_million=1, reasoning_per_million=3,
               currency="USD", pricing_version="test")
    row.update(overrides)
    monkeypatch.setattr(api.connection, "execute_query_one", lambda *_a, **_kw: row)


def test_price_does_not_charge_detail_tokens_twice(monkeypatch):
    pricing(monkeypatch)
    result = api._price("provider", "model", dict(prompt_tokens=100, completion_tokens=50,
                                                 cached_tokens=40, reasoning_tokens=20))
    assert result["cost"] == "0.000340"


def test_missing_detail_tariff_uses_regular_rate(monkeypatch):
    pricing(monkeypatch, cache_per_million=None, reasoning_per_million=None)
    assert api._price("p", "m", dict(prompt_tokens=100, completion_tokens=50,
                                    cached_tokens=40, reasoning_tokens=20))["cost"] == "0.000400"


@pytest.mark.parametrize("changes", [dict(prompt_tokens=None), dict(cached_tokens=101),
                                      dict(completion_tokens=None), dict(reasoning_tokens=51)])
def test_incomplete_or_inconsistent_usage_is_not_zero_cost(monkeypatch, changes):
    pricing(monkeypatch)
    usage = dict(prompt_tokens=100, completion_tokens=50, cached_tokens=40, reasoning_tokens=20)
    usage.update(changes)
    assert api._price("p", "m", usage)["cost"] is None
