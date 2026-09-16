"""Diagnostic results must reflect server observations, including missing data."""
import pytest
from pydantic import ValidationError

from lib import continuity_diagnostics as diagnostics,continuity_assembly as assembly
from .test_continuity_work import database
from .test_continuity_handoff import fixture
from .test_continuity_assembly import context_db,assembly_request


@pytest.fixture
def diagnostic_db(context_db):
    db,wid=context_db
    for sql in diagnostics.schema_statements('pg'):
        db.execute(sql)
    db.commit()
    return db,wid


def request(**kwargs):
    return dict(request_id='diagnostic',security_domain_id='domain',purpose='Test observations',idempotency_key='diagnostic',**kwargs)


def test_capabilities_distinguish_available_contracts_from_observed_execution(diagnostic_db):
    db,wid=diagnostic_db
    value=diagnostics.capabilities('owner',{'security_domain_id':'domain'})
    assert value['sources']['GRAPH']=='CAPTURED_NATIVE_PROJECTION'
    assert value['sources']['KNOWLEDGE']=='PROMOTED_ARTIFACT_ONLY'
    assert value['runtime_verification']=='UNOBSERVED'
    assert 'capabilities' in value['operations']
    assert value['entrypoint_parity']=='UNOBSERVED'
    assert value['managed_skill_runtime']=='COOPERATIVE_LINUX'
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        diagnostics.capabilities('owner',{'security_domain_id':'domain'})


def test_version_metadata_is_observed_without_exposing_driver_errors(diagnostic_db,monkeypatch):
    monkeypatch.setattr(diagnostics.connection,'database_version_observation',lambda:'18.6',raising=False)
    value=diagnostics.capabilities('owner',{'security_domain_id':'domain'})
    assert value['database_version']==dict(status='PASS',version='18.6',detail_code='DATABASE_SERVER_METADATA')
    def denied(): raise RuntimeError('Synthetic private connection detail')
    monkeypatch.setattr(diagnostics.connection,'database_version_observation',denied)
    value=diagnostics.capabilities('owner',{'security_domain_id':'domain'})
    assert value['database_version']['status']=='UNAVAILABLE'
    assert 'private' not in str(value)


def test_observed_checks_and_default_missing_checks_are_distinct(diagnostic_db):
    db,wid=diagnostic_db
    result=diagnostics.run_diagnostics('owner',request(checks=['PRINCIPAL','DOMAIN','DATABASE']))
    assert result['status']=='PASS'
    assert diagnostics.run_diagnostics('owner',request(checks=['PRINCIPAL','DOMAIN','DATABASE']))['replayed']
    incomplete=diagnostics.run_diagnostics('owner',dict(request(),idempotency_key='all'))
    assert incomplete['status']=='UNOBSERVED'
    assert [item for item in incomplete['checks'] if item['check_code']=='ENTRYPOINT_PARITY'][0]['status']=='UNOBSERVED'


def test_client_cannot_supply_success_or_observation(diagnostic_db):
    with pytest.raises(ValidationError):
        diagnostics.run_diagnostics('owner',dict(request(),status='PASS'))
    with pytest.raises(ValidationError):
        diagnostics.run_diagnostics('owner',dict(request(),observed=True))
    with pytest.raises(ValidationError):
        diagnostics.run_diagnostics('owner',request(checks=['PRINCIPAL','PRINCIPAL']))


def test_prepared_context_is_not_a_successful_input_receipt(diagnostic_db):
    db,wid=diagnostic_db
    context=assembly.assemble('owner',assembly_request(wid))
    value=request(checks=['CONTEXT_INPUT'],assembly_id=context['assembly_id'])
    assert diagnostics.run_diagnostics('owner',value)['status']=='UNOBSERVED'
    assembly.consume('owner',context['assembly_id'],lambda text:'observed synthetic response')
    assert diagnostics.run_diagnostics('owner',dict(value,idempotency_key='after-send'))['status']=='PASS'


def test_missing_table_is_recorded_without_poisoning_transaction(diagnostic_db):
    db,wid=diagnostic_db
    # A query failure rolls back to its savepoint, so the next real observation
    # and the diagnosis itself can still commit (also tested on PostgreSQL).
    result=diagnostics.run_diagnostics('owner',request(checks=['INSTANCE','DATABASE'],instance_id='absent'))
    assert result['status']=='UNAVAILABLE'
    assert result['checks'][0]['detail_code']=='CHECK_SERVICE_UNAVAILABLE'
    assert result['checks'][1]['status']=='PASS'
    assert 'SELECT' not in str(result)


def test_skill_acknowledgement_does_not_prove_runtime_switch(diagnostic_db):
    db,_=diagnostic_db
    db.executescript('''
        CREATE TABLE CX_UPGRADE_PLANS(UPGRADE_ID TEXT,SIGNATURE_STATE TEXT,PACKAGE_VERSION TEXT,PACKAGE_DIGEST TEXT);
        CREATE TABLE CX_SKILL_DISTRIBUTION(DISTRIBUTION_ID TEXT,UPGRADE_ID TEXT,AGENT_ID TEXT,MESSAGE_STATE TEXT,
          ACKNOWLEDGEMENT_STATE TEXT,ACTIVATION_STATE TEXT,DRIFT_STATE TEXT,SKILL_VERSION TEXT);
        INSERT INTO CX_SKILL_DISTRIBUTION VALUES('delivery','upgrade','owner','SENT','ACKNOWLEDGED','ACTIVE','IN_SYNC','4.4.15');
    ''')
    db.execute("INSERT INTO CX_UPGRADE_PLANS VALUES('upgrade','VERIFIED','4.4.15',?)",('a'*64,))
    db.commit()
    result=diagnostics.run_diagnostics('owner',request(checks=['SKILL_DELIVERY'],distribution_id='delivery'))
    assert result['status']=='UNOBSERVED'
    assert result['checks'][0]['detail_code']=='RUNTIME_SWITCH_NOT_OBSERVED'


def test_diagnostic_scope_revocation_and_audit_atomicity(diagnostic_db,monkeypatch):
    db,wid=diagnostic_db
    result=diagnostics.run_diagnostics('owner',request(checks=['DATABASE']))
    with pytest.raises(PermissionError):
        diagnostics.read_run('agent',result['run_id'])
    def fail(*args):
        raise RuntimeError('Audit failed')
    monkeypatch.setattr(diagnostics.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        diagnostics.run_diagnostics('owner',dict(request(checks=['DATABASE']),idempotency_key='rollback'))
    assert db.execute('SELECT COUNT(*) FROM CX_DIAGNOSTIC_RUNS').fetchone()[0]==1
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        diagnostics.read_run('owner',result['run_id'])
