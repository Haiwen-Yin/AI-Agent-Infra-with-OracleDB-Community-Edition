"""Fail-closed checkpoint recovery contracts; live gates cover actual Oracle DDL."""
from contextlib import nullcontext
import pytest
from lib.oracle_task_migration import TaskMigration, BACKUP, OLD, identifier


def test_database_identifier_rejects_sql_injection():
    with pytest.raises(ValueError):
        identifier('TASK_STEPS; DROP TABLE TEST')
    assert identifier('TASK_STEPS') == '"TASK_STEPS"'


@pytest.mark.parametrize('old_present', [True, False])
def test_resume_after_rename_or_old_drop_never_recopies_from_new_source(monkeypatch, old_present):
    migration = object.__new__(TaskMigration)
    calls = []
    monkeypatch.setattr(migration, 'setup', lambda: None)
    monkeypatch.setattr(migration, 'owner_lock', nullcontext)
    monkeypatch.setattr(migration, 'status', lambda: ('CUTOVER', 'OLD_DROPPED'))
    monkeypatch.setattr(migration, 'saved_inventory', lambda: {'saved': True})
    monkeypatch.setattr(migration, 'exists', lambda name: name == BACKUP or (name == OLD and old_present))
    monkeypatch.setattr(migration, 'scalar', lambda sql: 'HASH')
    monkeypatch.setattr(migration, 'switch', lambda inv: calls.append(inv))
    monkeypatch.setattr(migration, 'copy', lambda: pytest.fail('Recovery must not recopy or replace the backup'))
    migration.run()
    assert calls == [{'saved': True}]


def test_idempotent_completed_migration_checks_structure_without_touching_backup(monkeypatch):
    migration = object.__new__(TaskMigration)
    checks = []
    monkeypatch.setattr(migration, 'setup', lambda: None)
    monkeypatch.setattr(migration, 'owner_lock', nullcontext)
    monkeypatch.setattr(migration, 'status', lambda: ('VERIFIED', 'VERIFIED'))
    monkeypatch.setattr(migration, 'saved_inventory', lambda: {'saved': True})
    monkeypatch.setattr(migration, 'exists', lambda _: False)
    monkeypatch.setattr(migration, 'verify_structure', lambda inv: checks.append(inv))
    monkeypatch.setattr(migration, 'switch', lambda _: pytest.fail('Completed migration must not replay DDL'))
    assert migration.run() == {'state': 'VERIFIED', 'already_applied': True}
    assert checks == [{'saved': True}]


def test_copy_digest_mismatch_prevents_switch(monkeypatch):
    migration = object.__new__(TaskMigration)
    class Connection:
        def commit(self):
            pass
        def rollback(self):
            pass
    migration.conn = Connection()
    monkeypatch.setattr(migration, 'execute', lambda sql: None)
    monkeypatch.setattr(migration, 'digest', lambda table: {'count': 1, 'sha256': table})
    with pytest.raises(ValueError, match='differs'):
        migration.verify_copy()
