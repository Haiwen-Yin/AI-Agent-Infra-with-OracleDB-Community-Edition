"""Transport identity, typed requests, safe failures and MCP integration."""
import asyncio
import json
import httpx
import pytest

from lib import continuity_client as client,mcp_server


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('CX_CONTINUITY_GATEWAY_URL','http://synthetic.test/api/agent-gateway/continuity')
    monkeypatch.setenv('CX_AGENT_ACCESS_TOKEN','synthetic-secret')
    monkeypatch.setenv('CX_AGENT_INSTANCE_ID','synthetic-instance')


def test_exact_actor_header_and_revision_are_forwarded(configured):
    observed=[]
    def transport(request):
        observed.append(request)
        return httpx.Response(200,json={'work_contract_id':'work','revision_no':2})
    value={'operation':'work_read','request':{'work_id':'work','revision':2}}
    result=client.call('registered-agent',value,transport=httpx.MockTransport(transport))
    assert result['revision_no']==2
    request=observed[0]
    assert request.headers['x-agent-id']=='registered-agent'
    assert request.headers['x-agent-instance']=='synthetic-instance'
    assert request.headers['authorization']=='Bearer synthetic-secret'
    assert request.url.path=='/api/agent-gateway/continuity/work-contracts/work'
    assert request.url.params['revision']=='2'


@pytest.mark.parametrize('value',[
    {'operation':'work_read','request':{'work_id':'work','principal_id':'victim'}},
    {'operation':'work_read','request':{'work_id':'work'},'gateway_url':'https://untrusted.test'},
    {'operation':'unknown','request':{}},
    {'operation':'candidate_promote','request':{'candidate_id':'candidate'}},
])
def test_invalid_or_spoofed_call_never_reaches_transport(configured,value):
    def transport(request):
        pytest.fail('Invalid input reached network')
    with pytest.raises(client.ContinuityClientError,match='INVALID_REQUEST'):
        client.call('agent',value,transport=httpx.MockTransport(transport))


@pytest.mark.parametrize('status,code',[(401,'UNAUTHENTICATED'),(403,'ACCESS_DENIED'),(409,'CONFLICT'),(422,'INVALID_REQUEST'),(302,'GATEWAY_UNAVAILABLE'),(503,'GATEWAY_UNAVAILABLE')])
def test_errors_are_sanitized_and_redirects_never_receive_credentials(configured,status,code):
    calls=[]
    def transport(request):
        calls.append(request)
        return httpx.Response(status,headers={'Location':'https://untrusted.test'},text='sensitive driver details')
    with pytest.raises(client.ContinuityClientError) as caught:
        client.call('agent',{'operation':'work_read','request':{'work_id':'work'}},transport=httpx.MockTransport(transport))
    assert caught.value.code==code and len(calls)==1
    assert 'sensitive' not in str(caught.value) and 'secret' not in str(caught.value)


def test_unknown_delivery_is_not_retried(configured):
    calls=[]
    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout('synthetic-secret')
    with pytest.raises(client.ContinuityClientError,match='GATEWAY_UNAVAILABLE'):
        client.call('agent',{'operation':'work_read','request':{'work_id':'work'}},transport=httpx.MockTransport(transport))
    assert len(calls)==1


def test_default_installation_exposes_typed_continuity_contract(monkeypatch):
    from lib.config import MCPConfig
    assert 'continuity' in MCPConfig().exposed_tools
    monkeypatch.setattr(mcp_server,'_authenticated_mcp_agent',lambda:'registered-agent')
    monkeypatch.setattr(mcp_server,'_get_exposed_tools',lambda:list(MCPConfig().exposed_tools))
    monkeypatch.setattr(mcp_server,'_load_dynamic_tools',lambda:[])
    tools=asyncio.run(mcp_server.list_tools())
    continuity=next(tool for tool in tools if tool.name=='continuity')
    assert continuity.inputSchema==client.input_schema()


def test_mcp_uses_authenticated_identity_and_respects_exposure(monkeypatch):
    monkeypatch.setattr(mcp_server,'_authenticated_mcp_agent',lambda:'registered-agent')
    monkeypatch.setattr(mcp_server,'_get_exposed_tools',lambda:['continuity'])
    observed=[]
    def call(actor,value):
        observed.append((actor,value))
        return {'status':'UNOBSERVED'}
    monkeypatch.setattr(client,'call',call)
    value={'operation':'diagnostics_run','request':{}}
    result=asyncio.run(mcp_server.call_tool('continuity',value))
    assert observed==[('registered-agent',value)] and json.loads(result[0].text)['status']=='UNOBSERVED'
    monkeypatch.setattr(mcp_server,'_get_exposed_tools',lambda:[])
    result=asyncio.run(mcp_server.call_tool('continuity',value))
    assert json.loads(result[0].text)['error']=='TOOL_NOT_EXPOSED' and len(observed)==1
