"""CLI shares Gateway identity, diagnostics and fail-closed exit semantics."""
import json

import httpx
import pytest

from lib import continuity_cli as cli


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('AI_AGENT_ID','synthetic-agent')
    monkeypatch.setenv('CX_CONTINUITY_GATEWAY_URL','http://synthetic.test/api/agent-gateway/continuity')
    monkeypatch.setenv('CX_AGENT_ACCESS_TOKEN','synthetic-secret')
    monkeypatch.setenv('CX_AGENT_INSTANCE_ID','synthetic-instance')


@pytest.mark.parametrize('command,status,exit_code',[
    ('setup','PASS',0),('setup','FAIL',1),('doctor','UNOBSERVED',1),('doctor','UNAVAILABLE',1),
])
def test_diagnostics_preserve_server_status(configured,capsys,command,status,exit_code):
    def send(request):
        body=json.loads(request.content)
        assert body['instance_id']=='synthetic-instance'
        assert request.headers['x-agent-id']=='synthetic-agent'
        assert 'INSTANCE' in body['checks']
        assert ('ENTRYPOINT_PARITY' in body['checks'])==(command=='doctor')
        return httpx.Response(200,json={'run_id':'run','status':status})
    assert cli.main([command,'--domain','domain'],transport=httpx.MockTransport(send))==exit_code
    assert json.loads(capsys.readouterr().out)['status']==status


def test_verify_context_requires_explicit_evidence(configured,capsys):
    def send(request):
        pytest.fail('Missing evidence must not be submitted')
    assert cli.main(['verify-context','--domain','domain','--purpose','Check'],transport=httpx.MockTransport(send))==1
    assert json.loads(capsys.readouterr().out)['error']=='CONTEXT_REFERENCE_REQUIRED'


def test_verify_context_does_not_equate_preparation_with_delivery(configured,capsys):
    def send(request):
        body=json.loads(request.content)
        assert body['assembly_id']=='prepared' and 'CONTEXT_INPUT' in body['checks']
        return httpx.Response(200,json={'status':'UNOBSERVED'})
    assert cli.main(['verify-context','--domain','domain','--purpose','Check','--assembly-id','prepared'],transport=httpx.MockTransport(send))==1
    assert json.loads(capsys.readouterr().out)['status']=='UNOBSERVED'


def test_capabilities_come_from_authorized_server(configured,capsys):
    def send(request):
        assert request.method=='GET' and request.url.params['security_domain_id']=='domain'
        return httpx.Response(403,text='sensitive-secret')
    assert cli.main(['capabilities','--domain','domain'],transport=httpx.MockTransport(send))==1
    assert json.loads(capsys.readouterr().out)=={'error':'ACCESS_DENIED'}


def test_call_rejects_identity_override_and_sanitizes_file_failures(configured,capsys,tmp_path):
    path=tmp_path/'request.json'
    path.write_text(json.dumps({'operation':'work_read','request':{'work_id':'w','principal_id':'other'}}))
    def send(request):
        pytest.fail('Invalid request must not reach network')
    assert cli.main(['call','--request-file',str(path)],transport=httpx.MockTransport(send))==1
    assert json.loads(capsys.readouterr().out)=={'error':'INVALID_REQUEST'}
    assert cli.main(['call','--request-file',str(tmp_path/'secret-missing')])==1
    assert json.loads(capsys.readouterr().out)=={'error':'INVALID_REQUEST'}
