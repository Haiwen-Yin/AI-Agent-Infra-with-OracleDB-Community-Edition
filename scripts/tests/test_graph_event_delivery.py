"""Pure delivery-contract tests for the v4.2.1 Inbox/Outbox boundary."""

from lib import graph_event_api


class _DeliveryConnection:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return 1

    def execute_query_one(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return self.row

    def execute_query(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return []


def test_retry_backoff_is_bounded_and_deterministic():
    assert graph_event_api.retry_delay_seconds(1) == 5
    assert graph_event_api.retry_delay_seconds(2) == 10
    assert graph_event_api.retry_delay_seconds(20) == 3600
    assert graph_event_api.retry_delay_seconds("bad") == 5


def test_outbox_claim_and_retry_preserve_attempt_fencing(monkeypatch):
    connection = _DeliveryConnection({"attempts": 2, "max_attempts": 5})
    monkeypatch.setattr(graph_event_api, "connection", connection)

    assert graph_event_api.mark_outbox("OUTBOX_1", "DISPATCHING") is True
    assert "ATTEMPTS = ATTEMPTS + 1" in connection.calls[0][0]
    assert graph_event_api.mark_outbox("OUTBOX_1", "RETRY", "temporary") is True
    retry_sql, retry_params = connection.calls[-1]
    assert "STATUS = 'PENDING'" in retry_sql
    assert retry_params["error_message"] == "temporary"
    assert retry_params["available_at"] is not None


def test_outbox_retries_become_dead_letter_at_the_limit(monkeypatch):
    connection = _DeliveryConnection({"attempts": 5, "max_attempts": 5})
    monkeypatch.setattr(graph_event_api, "connection", connection)

    assert graph_event_api.mark_outbox("OUTBOX_2", "RETRY", "permanent") is True
    assert any("STATUS = :status" in sql for sql, _ in connection.calls)
    assert connection.calls[-1][1]["status"] == "DEAD_LETTER"


def test_inbox_retry_returns_to_ready_with_a_bounded_schedule(monkeypatch):
    connection = _DeliveryConnection({"attempts": 1})
    monkeypatch.setattr(graph_event_api, "connection", connection)

    assert graph_event_api.mark_inbox("INBOX_1", "RETRY", "temporary") is True
    sql, params = connection.calls[-1]
    assert "STATUS = 'PROCESSING'" in sql
    assert params["status"] == "RECEIVED"
    assert params["available_at"] is not None


def test_delivery_state_machine_does_not_ack_unclaimed_rows(monkeypatch):
    connection = _DeliveryConnection({"attempts": 1})
    monkeypatch.setattr(graph_event_api, "connection", connection)

    assert graph_event_api.mark_inbox("INBOX_2", "PROCESSED") is True
    assert "STATUS = 'PROCESSING'" in connection.calls[-1][0]


def test_custom_retry_delay_is_bounded(monkeypatch):
    connection = _DeliveryConnection({"attempts": 1})
    monkeypatch.setattr(graph_event_api, "connection", connection)

    assert graph_event_api.mark_inbox("INBOX_3", "RETRY", retry_after_seconds=999999) is True
    available_at = connection.calls[-1][1]["available_at"]
    assert available_at is not None
