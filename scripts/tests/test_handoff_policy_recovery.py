"""Interrupted additive DDL must resume without trusting uncommitted history."""
from pathlib import Path
import pytest
import migration_runner as runner


@pytest.mark.parametrize('database',['oracle','pg','yashandb'])
@pytest.mark.parametrize('state',['FAILED','RUNNING','APPLIED','ABSENT','CHANGED','PREREQUISITE'])
def test_successor_recovery_is_checksum_bound(monkeypatch,database,state):
    numbers=[number for number in range(85,94) if number!=92 or database=='yashandb']
    scripts=[Path(str(number)+'_predecessor.sql') for number in numbers]+[Path('94_v4_4_15_handoff_policy.sql')]
    closed=[]
    class Probe:
        def cursor(self): return self
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def close(self): closed.append(True)
    monkeypatch.setattr(runner,'_connect_for_preflight',lambda *_:Probe())
    monkeypatch.setattr(runner,'_schema_tables',lambda *_:{'AI_SCHEMA_MIGRATION_STEPS'})
    monkeypatch.setattr(runner,'_checksum',lambda path:path.name)
    def row(_cursor,_database,path):
        if path==scripts[-1]:
            if state=='ABSENT': return None
            return {'status':state if state in {'FAILED','RUNNING','APPLIED'} else 'FAILED',
                    'checksum':'changed' if state=='CHANGED' else path.name}
        return {'status':'FAILED' if state=='PREREQUISITE' else 'APPLIED','checksum':path.name}
    monkeypatch.setattr(runner,'_step_row',row)
    if state in {'CHANGED','PREREQUISITE'}:
        with pytest.raises(ValueError): runner._order_successor_recovery(database,{},scripts)
    else:
        actual=runner._order_successor_recovery(database,{},scripts)
        assert actual==([scripts[-1],*scripts] if state in {'FAILED','RUNNING'} else scripts)
    assert closed==[True]
