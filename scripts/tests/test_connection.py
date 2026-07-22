"""AI Agent Infra v4.0.1 - Connection Pool Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.connection import (
    get_pool, get_connection, execute, execute_query,
    execute_query_one, close_pool, scalar_select_suffix,
)


def test_pool_init():
    pool = get_pool()
    assert pool is not None
    assert pool.min == 2
    assert pool.max == 5
    print("PASS: test_pool_init")


def test_get_connection():
    with get_connection() as conn:
        assert conn is not None
        cur = conn.cursor()
        cur.execute(f"SELECT 1{scalar_select_suffix()}")
        result = cur.fetchone()
        assert result[0] == 1
    print("PASS: test_get_connection")


def test_execute_query():
    rows = execute_query(f"SELECT 1 AS val{scalar_select_suffix()}")
    assert len(rows) == 1
    assert rows[0]["val"] == 1
    print("PASS: test_execute_query")


def test_execute_query_one():
    row = execute_query_one(f"SELECT 42 AS answer{scalar_select_suffix()}")
    assert row is not None
    assert row["answer"] == 42
    print("PASS: test_execute_query_one")


def test_execute_dml():
    sql = f"SELECT 1{scalar_select_suffix()}"
    result = execute(sql)
    assert isinstance(result, int)
    print("PASS: test_execute_dml")


def test_close_pool():
    close_pool()
    from lib import connection
    connection._pool = None
    pool2 = get_pool()
    assert pool2 is not None
    print("PASS: test_close_pool")


def run_all():
    tests = [
        test_pool_init,
        test_get_connection,
        test_execute_query,
        test_execute_query_one,
        test_execute_dml,
        test_close_pool,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} - {e}")
            failed += 1
    close_pool()
    print(f"\nConnection Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
