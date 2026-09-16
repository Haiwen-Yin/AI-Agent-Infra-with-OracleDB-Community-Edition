"""Release verification must fail closed on absent or failed step evidence."""
import pytest
from lib import deployment_orchestrator as deployment


class Cursor:
    def __init__(self, terminal, failed, missing):
        self.terminal, self.failed, self.missing = terminal, failed, missing

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if self.missing:
            raise RuntimeError("step ledger missing")
        assert "AI_SCHEMA_MIGRATION_STEPS" in sql
        self.value = self.failed if "STATUS='FAILED'" in sql else self.terminal

    def fetchone(self):
        return (self.value,)


class Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


@pytest.mark.parametrize("database", ["pg", "yashandb"])
@pytest.mark.parametrize("terminal,failed,missing,passed", [
    (1, 0, False, True), (0, 0, False, False),
    (1, 1, False, False), (1, 0, True, False),
])
def test_postflight_requires_real_step_evidence(monkeypatch, database, terminal, failed, missing, passed):
    monkeypatch.setattr(deployment, "_connect", lambda *_: Connection(Cursor(terminal, failed, missing)))
    result = deployment.postflight(database, "community", {}, "82_v4_4_14_governed_model_capabilities.sql")
    assert result["passed"] is passed


def test_v415_uses_journaled_migration_execution():
    import migration_runner
    assert "4.4.15" in migration_runner.JOURNALED_MIGRATION_VERSIONS


@pytest.mark.parametrize('database',['pg','oracle','yashandb'])
def test_standalone_journal_lookup_uses_explicit_package_version(monkeypatch,database):
    import migration_runner as runner
    from pathlib import Path
    monkeypatch.setattr(runner,'MIGRATION_VERSION','4.1.0')
    class Journal:
        def execute(self,sql,params):
            selected=params[0] if isinstance(params,tuple) else params['version']
            self.row=('exact-checksum','APPLIED',1,0) if selected=='4.4.15' else None
        def fetchone(self): return self.row
    cursor=Journal()
    script=Path('94_v4_4_15_handoff_policy.sql')
    assert runner._step_row(cursor,database,script) is None
    assert runner._step_row(cursor,database,script,version='4.4.15')['status']=='APPLIED'
    assert runner.MIGRATION_VERSION=='4.1.0'


@pytest.mark.parametrize('database', ['oracle','pg','yashandb'])
@pytest.mark.parametrize('missing', ['table','column',None])
def test_newer_migrations_do_not_mask_missing_historical_queue(monkeypatch,database,missing):
    import migration_runner as runner
    from pathlib import Path
    tables={'EXECUTION_JOBS','EXECUTION_ATTEMPTS','EXECUTION_POLICIES','EXECUTION_ARTIFACTS','EXECUTION_AUDIT'}
    if missing=='table':
        tables.remove('EXECUTION_JOBS')
    monkeypatch.setattr(runner,'_schema_tables',lambda *_:tables)
    class AllColumns:
        def __ge__(self,required):
            return True
    monkeypatch.setattr(runner,'_schema_columns',lambda _cursor,_db,table:
                        set() if missing=='column' and table=='EXECUTION_AUDIT' else AllColumns())
    assert runner._step_objects_complete(None,database,Path('7_v4_0_1_migration.sql')) is (missing is None)


@pytest.mark.parametrize("error,code", [
    (RuntimeError("YAS-20001 load yacli library error [libyascli.so: cannot open shared object file]"),
     "YASHANDB_CLIENT_UNAVAILABLE"),
    (ModuleNotFoundError("No module named 'yaspy'"), "YASHANDB_CLIENT_UNAVAILABLE"),
    (RuntimeError("connection refused password=private-value"), "DATABASE_CONNECTION_FAILED"),
])
def test_yashan_preflight_distinguishes_local_client_from_server_failure(monkeypatch, error, code):
    def fail(*args):
        raise error
    monkeypatch.setattr(deployment, "_connect", fail)
    result = deployment.preflight("yashandb", {})
    assert not result["passed"]
    check = result["blocked"][0]
    assert check["detail"]["error_code"] == code
    assert ("install_yaspy.sh" in check["remediation"]) == (code == "YASHANDB_CLIENT_UNAVAILABLE")
    assert "private-value" not in str(result)
