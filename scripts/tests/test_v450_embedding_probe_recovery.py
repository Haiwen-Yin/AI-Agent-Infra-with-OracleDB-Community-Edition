"""Provider recovery must update readiness without granting write authority."""
import io
import json
import urllib.error

import pytest
from lib import embedding_governance as eg


@pytest.mark.parametrize('failure,changed', [(False, False), (True, False), (False, True)])
def test_provider_recovery_is_version_bound_and_audited(monkeypatch, failure, changed):
    profile = dict(profile_id='EP_TEST', version=3, execution_mode='PLATFORM_MANAGED',
                   provider_url='http://127.0.0.1/v1', model_id='embedding', dimension=2)
    monkeypatch.setattr(eg, '_profile_row', lambda _: profile)
    monkeypatch.setattr(eg, '_profile_api_key', lambda _: '')
    monkeypatch.setattr(eg, '_physical_dimension', lambda _: 2)
    def provider(*args, **kwargs):
        if failure:
            raise urllib.error.URLError('provider unavailable')
        return io.BytesIO(json.dumps({'model': 'embedding', 'data': [{'embedding': [0.1, 0.2]}]}).encode())
    monkeypatch.setattr(eg.urllib.request, 'urlopen', provider)
    statements, audits = [], []
    class Tx:
        def query_one(self, sql, params):
            assert 'FOR UPDATE' in sql
            return {'version': 4 if changed else 3, 'status': 'ACTIVE'}
        def execute(self, sql, params):
            statements.append((sql, params))
    monkeypatch.setattr(eg.connection, 'execute_transaction_callback', lambda work: work(Tx()))
    monkeypatch.setattr(eg, '_audit', lambda *args: audits.append(args))
    if changed:
        with pytest.raises(eg.EmbeddingConflict):
            eg.probe_profile('admin', 'EP_TEST')
        assert not statements and not audits
        return
    result = eg.probe_profile('admin', 'EP_TEST')
    assert result['status'] == ('FAILED' if failure else 'VERIFIED')
    space_sql, params = next(item for item in statements if item[0].startswith('UPDATE CX_EMBEDDING_SPACES'))
    assert params['state'] == result['status'] and params['profile'] == 'EP_TEST'
    assert 'WRITE_ENABLED' not in space_sql and 'CX_EMBEDDING_BINDINGS' not in space_sql
    assert "STATUS='ACTIVE'" in space_sql and 'DIMENSION=:dimension' in space_sql
    assert audits
