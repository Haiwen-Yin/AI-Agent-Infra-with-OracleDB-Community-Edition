"""Dynamic Tool transport must not fall back to direct control-table writes."""
import asyncio
import json
import pytest
from pydantic import ValidationError
from lib import mcp_server,continuity_client,tool_registry
from lib.continuity_contracts import ToolInvocation
from lib import continuity_tools
from decimal import Decimal


def test_reauthentication_after_nested_discovery_clears_previous_agent(monkeypatch):
    from lib import connection,agent_registration
    current=['previous-agent']
    monkeypatch.setenv('AI_AGENT_ID','actual-agent')
    monkeypatch.setenv('AI_AGENT_TOKEN','synthetic-registration')
    monkeypatch.setattr(connection,'set_agent_context',lambda value:current.__setitem__(0,value))
    def authenticate(actor,credential):
        assert current[0] is None
        return {'agent_id':actor}
    monkeypatch.setattr(agent_registration,'authenticate_agent',authenticate)
    assert mcp_server._authenticated_mcp_agent()=='actual-agent'
    assert current[0]=='actual-agent'
    monkeypatch.setattr(agent_registration,'authenticate_agent',lambda *_:None)
    with pytest.raises(PermissionError):
        mcp_server._authenticated_mcp_agent()
    assert current[0] is None


def test_native_json_number_roundtrip_keeps_tool_payload_digest():
    original={'timeout':10,'body':{'whole':1.0,'fraction':0.125,'large':9007199254740993}}
    oracle={'timeout':Decimal('10'),'body':{'whole':Decimal('1'),'fraction':Decimal('0.125'),'large':Decimal('9007199254740993')}}
    assert continuity_tools._digest(original)==continuity_tools._digest(oracle)
    assert continuity_tools._digest(original)!=continuity_tools._digest({**original,'timeout':11})


def test_dynamic_tool_uses_authenticated_gateway_identity(monkeypatch):
    calls=[]
    monkeypatch.setattr(mcp_server,'_authenticated_mcp_agent',lambda:'actual-agent')
    monkeypatch.setattr(continuity_client,'call',lambda actor,value:calls.append((actor,value)) or {'success':True,'job_id':'job'})
    def direct(*args,**kwargs):
        pytest.fail('Dynamic MCP must not write the execution queue through an Agent database login')
    monkeypatch.setattr(tool_registry,'invoke_tool',direct)
    arguments={'security_domain_id':'domain','arguments':{'item':'synthetic'},'reason':'Explicit request','idempotency_key':'request'}
    result=asyncio.run(mcp_server.call_tool('DYN_tool',arguments))
    assert json.loads(result[0].text)['job_id']=='job'
    assert calls==[('actual-agent',{'operation':'tool_invoke','request':{**arguments,'tool_id':'tool'}})]


def test_gateway_failure_does_not_fall_back_to_owner_or_direct_sql(monkeypatch):
    monkeypatch.setattr(mcp_server,'_authenticated_mcp_agent',lambda:'actual-agent')
    def unavailable(*args):
        raise continuity_client.ContinuityClientError('UNAUTHENTICATED')
    monkeypatch.setattr(continuity_client,'call',unavailable)
    result=asyncio.run(mcp_server.call_tool('DYN_tool',{}))
    assert json.loads(result[0].text)=={'success':False,'error':'UNAUTHENTICATED'}


@pytest.mark.parametrize('change',[
    {'timeout':True},{'timeout':121},{'principal_id':'victim'},
    {'arguments':{'oversized':'x'*65537}}, {'arguments':{'value':float('nan')}},
])
def test_tool_request_rejects_identity_override_and_unbounded_input(change):
    request=dict(security_domain_id='domain',arguments={},reason='Explicit request',idempotency_key='request')
    with pytest.raises(ValidationError):
        ToolInvocation.model_validate({**request,**change})
