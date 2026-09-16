"""HTTP contract tests; live session/CSRF acceptance remains a separate gate."""
from contextlib import nullcontext

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from lib.continuity_http import install_routes
from lib import continuity_work as work
from .test_continuity_work import database, request
from .test_continuity_handoff import fixture
from .test_continuity_assembly import context_db, assembly_request


@pytest.fixture
def http(context_db):
    app=FastAPI()
    state={'actor':'owner','allowed':True,'calls':[]}
    def guard(action):
        def dependency():
            state['calls'].append(action)
            if not state['allowed']:
                raise HTTPException(403,'Denied')
            return {'principal_id':state['actor']}
        return dependency
    install_routes(app,guard,nullcontext)
    with TestClient(app) as client:
        yield client,state,context_db


def test_typed_http_create_conflict_and_body_cannot_override_actor(http):
    client,state,(db,wid)=http
    response=client.post('/api/work-contracts',json=request('http'))
    assert response.status_code==200
    created=response.json()['work_contract_id']
    assert client.get('/api/work-contracts/'+created).status_code==200
    assert client.post('/api/work-contracts',json=dict(request('evil'),principal_id='outsider')).status_code==422
    change=dict(expected_version=2,content=request()['content'],reason='stale',idempotency_key='stale')
    response=client.post('/api/work-contracts/'+created+'/revisions',json=change)
    assert response.status_code==409 and response.json()['detail']['code']=='STALE_VERSION'
    state['actor']='outsider'
    assert client.get('/api/work-contracts/'+created).status_code==403


def test_http_dependency_runs_before_service_and_driver_error_is_sanitized(http,monkeypatch):
    client,state,(db,wid)=http
    state['allowed']=False
    assert client.post('/api/work-contracts',json=request('blocked')).status_code==403
    assert state['calls']==['workspaces.write']
    state['allowed']=True
    def fail(*args):
        raise RuntimeError('sensitive SQL and credentials')
    monkeypatch.setattr(work,'read_work',fail)
    response=client.get('/api/work-contracts/'+wid)
    assert response.status_code==503
    assert 'sensitive' not in response.text and 'credentials' not in response.text


def test_http_prepared_context_has_no_delivery_receipt(http):
    client,state,(db,wid)=http
    response=client.post('/api/context/assemble',json=assembly_request(wid))
    assert response.status_code==200
    aid=response.json()['assembly_id']
    items=client.get('/api/context/assemblies/'+aid+'/items')
    assert items.status_code==200 and len(items.json()['items'])==1
    assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_INPUT_USES').fetchone()[0]==0


def test_http_parallel_policy_is_versioned_and_owner_bound(http):
    client,state,(db,wid)=http
    body=dict(expected_version=1,max_active_recipients=2,reason='Explicit concurrency',idempotency_key='parallel-http')
    path='/api/work-contracts/'+wid+'/handoff-policy'
    assert client.post(path,json=body).status_code==200
    assert client.get('/api/work-contracts/'+wid).json()['handoff_policy']['max_active_recipients']==2
    assert client.post(path,json=body).json()['replayed']
    assert client.post(path,json={**body,'max_active_recipients':3}).status_code==409
    state['actor']='outsider'
    assert client.post(path,json={**body,'expected_version':2,'idempotency_key':'denied'}).status_code==403
