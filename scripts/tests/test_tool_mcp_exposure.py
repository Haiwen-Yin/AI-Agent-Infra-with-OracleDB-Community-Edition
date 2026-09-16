"""Operator exposure decisions must remain authorized, conditional and atomic."""
import pytest
from lib import tool_registry as tools,identity_api as identity
from .test_continuity_work import database


@pytest.fixture
def registry(database):
    database.execute('CREATE TABLE TOOL_REGISTRY(TOOL_ID TEXT PRIMARY KEY,STATUS TEXT,MCP_EXPOSED TEXT,UPDATED_AT TIMESTAMP)')
    database.execute("INSERT INTO TOOL_REGISTRY VALUES('synthetic','ACTIVE','N',CURRENT_TIMESTAMP)")
    database.commit()
    return database


def test_current_exposure_and_status_are_checked(registry):
    assert tools.set_mcp_exposure('owner','synthetic',expected_exposed=False,exposed=True,reason='Expose verified tool')['mcp_exposed']
    with pytest.raises(tools.ToolExposureConflict):
        tools.set_mcp_exposure('owner','synthetic',expected_exposed=False,exposed=False,reason='Stale view')
    assert not tools.set_mcp_exposure('owner','synthetic',expected_exposed=True,exposed=False,reason='Withdraw exposure')['mcp_exposed']
    registry.execute("UPDATE TOOL_REGISTRY SET STATUS='DEPRECATED'")
    registry.commit()
    with pytest.raises(tools.ToolExposureConflict):
        tools.set_mcp_exposure('owner','synthetic',expected_exposed=False,exposed=True,reason='Inactive tool')


def test_exposure_rechecks_permission_and_rolls_back_on_audit_failure(registry,monkeypatch):
    monkeypatch.setattr(identity,'effective_access',lambda *args,**kwargs:{'decision':'DENY'})
    with pytest.raises(PermissionError):
        tools.set_mcp_exposure('owner','synthetic',expected_exposed=False,exposed=True,reason='Denied')
    monkeypatch.setattr(identity,'effective_access',lambda *args,**kwargs:{'decision':'ALLOW'})
    def fail(*args):
        raise RuntimeError('Synthetic audit failure')
    monkeypatch.setattr(identity,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        tools.set_mcp_exposure('owner','synthetic',expected_exposed=False,exposed=True,reason='Audit rollback')
    assert registry.execute('SELECT MCP_EXPOSED FROM TOOL_REGISTRY').fetchone()[0]=='N'


@pytest.mark.parametrize('value',['Y',1,None])
def test_exposure_does_not_coerce_flags(registry,value):
    with pytest.raises(ValueError):
        tools.set_mcp_exposure('owner','synthetic',expected_exposed=False,exposed=value,reason='Invalid flag')
