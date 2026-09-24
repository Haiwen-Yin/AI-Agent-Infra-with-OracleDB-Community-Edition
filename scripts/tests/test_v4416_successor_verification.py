"""Application-only release verifies historical, checksum-bound schema evidence."""
from pathlib import Path

import pytest
import migration_runner as runner
from lib import continuity_schema_validation


@pytest.mark.parametrize('database', ['oracle', 'pg', 'yashandb'])
@pytest.mark.parametrize('edition', ['community', 'enterprise'])
def test_application_release_retains_complete_bootstrap_chain(monkeypatch, database, edition, tmp_path):
    monkeypatch.setattr(runner, '_v411_script_names', lambda *_: ['base.sql'])
    actual = runner.release_script_names('4.4.16', database, tmp_path, edition)
    assert actual == runner.release_script_names('4.4.15', database, tmp_path, edition)
    assert actual[-1] == '97_v4_4_15_native_context_sources.sql'
    assert '4.4.16' in runner.RUNTIME_ISOLATION_MIGRATION_VERSIONS


@pytest.mark.parametrize('current', [None, 'FAILED', 'APPLIED'])
@pytest.mark.parametrize('historical', ['APPLIED', 'FAILED', 'TAMPERED'])
def test_historical_successor_does_not_override_current_failure(monkeypatch, current, historical):
    root = Path(__file__).resolve().parents[2]
    deploy = root / 'adapters/pg/deploy' if (root / 'adapters').is_dir() else root / 'scripts/deploy'
    script = deploy / '86_v4_4_15_continuity_entities.sql'
    successor = deploy / '94_v4_4_15_handoff_policy.sql'
    calls = []

    def ledger(cursor, database, path, *, version=None):
        calls.append(version)
        state = current if version == '4.4.16' else historical
        if state is None:
            return None
        return {'status': state, 'checksum': runner._checksum(successor) if state != 'TAMPERED' else 'bad'}

    def validate(cursor, database, facts):
        retired_key = ['U', ['ACTIVE_WORK_ID'], '', []]
        return ['retired key'] if retired_key in facts['CX_HANDOFFS']['keys'] else []

    monkeypatch.setattr(runner, '_step_row', ledger)
    monkeypatch.setattr(continuity_schema_validation, 'errors', validate)
    assert runner._step_objects_complete(None, 'pg', script, version='4.4.16') == (
        current == 'APPLIED' or current is None and historical == 'APPLIED')
    assert calls == (['4.4.16', '4.4.15'] if current is None else ['4.4.16'])
