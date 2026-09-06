from lib.workspace_api import _sanitize_context_data


def test_secrets_in_nested_lists_are_redacted_without_mutating_input():
    source = {"steps": [{"arguments": [{"password": "secret", "nested": [[{"api_key": "key"}]]}],
                         "output": "kept"}], "count": 2}
    cleaned = _sanitize_context_data(source)
    assert cleaned["steps"][0]["arguments"][0]["password"] == "[REDACTED]"
    assert cleaned["steps"][0]["arguments"][0]["nested"][0][0]["api_key"] == "[REDACTED]"
    assert cleaned["steps"][0]["output"] == "kept"
    assert cleaned["count"] == 2
    assert source["steps"][0]["arguments"][0]["password"] == "secret"


def test_top_level_list_and_json_scalars():
    assert _sanitize_context_data([{"token": "x"}, None, True, 7, "text"]) == [
        {"token": "[REDACTED]"}, None, True, 7, "text"]
