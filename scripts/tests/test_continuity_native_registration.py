"""A newly provisioned PG Agent must not reopen control-plane history."""
import json
from pathlib import Path
import secrets

import pytest

from lib import connection,agent_api


def test_pg_registration_preserves_continuity_native_denials():
    if getattr(connection,'DATABASE_DIALECT','')!='postgresql':
        pytest.skip('PostgreSQL registration against a generated isolated edition required')
    from lib.config import get_config
    if str(get_config().database.dbname).lower() not in {'cxv415com','cxv415ent'}:
        pytest.skip('Continuity registration mutation requires the isolated release database')
    import psycopg2
    from psycopg2 import sql
    from lib.continuity_schema_validation import errors
    root=Path(__file__).resolve().parents[2]
    facts_path=root/'scripts/deploy/86_v4_4_15_continuity_entities.schema.json'
    assert facts_path.is_file(), 'The generated installation must carry the schema manifest'
    facts=json.loads(facts_path.read_text())
    bindings_path=facts_path.with_name('87_v4_4_15_continuity_bindings.schema.json')
    assert bindings_path.is_file(), 'The generated installation must carry the bindings manifest'
    facts.update(json.loads(bindings_path.read_text()))
    execution_links=facts_path.with_name('88_v4_4_15_execution_links.schema.json')
    assert execution_links.is_file()
    facts.update(json.loads(execution_links.read_text()))
    import migration_runner as runner
    runner.MIGRATION_VERSION='4.4.15'
    successors=[facts_path.with_name(name) for name in (
        '93_v4_4_15_mcp_tool_requests.sql','94_v4_4_15_handoff_policy.sql',
        '95_v4_4_15_runtime_context.sql','96_v4_4_15_runtime_credentials.sql',
        '97_v4_4_15_native_context_sources.sql')]
    with connection.get_connection() as owner:
        with owner.cursor() as cursor:
            # Validate the checksum-bound successor before replacing historical
            # key facts; do not silently remove a failing key from the test.
            assert runner._step_objects_complete(cursor,'pg',facts_path.with_name('86_v4_4_15_continuity_entities.sql'))
            for successor in successors:
                assert successor.is_file()
                journal=runner._step_row(cursor,'pg',successor)
                assert journal and journal['status']=='APPLIED' and journal['checksum']==runner._checksum(successor)
                assert runner._step_objects_complete(cursor,'pg',successor)
                facts.update(json.loads(successor.with_suffix('.schema.json').read_text()))
    assert 'CX_WORK_HANDOFF_POLICIES' in facts
    actor='AGENT_CX415ACL_'+secrets.token_hex(12).upper()
    connection.set_agent_context(None)
    login=None
    try:
        agent_api.register_agent(actor,'Synthetic continuity registration boundary',agent_type='test')
        login=agent_api._get_agent_login_credentials(actor)
        with connection.get_connection() as owner:
            with owner.cursor() as cursor:
                assert errors(cursor,'pg',facts)==[]
        native=psycopg2.connect(user=login['username'],password=login['password'],
            host=login['host'],port=login['port'],dbname=login['dbname'])
        try:
            for table in facts:
                for statement in ('SELECT 1 FROM {} WHERE 1=0','DELETE FROM {} WHERE 1=0'):
                    try:
                        with native.cursor() as cursor:
                            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                                cursor.execute(sql.SQL(statement).format(sql.Identifier('public',table.lower())))
                    finally:
                        native.rollback()
        finally:
            native.close()
    finally:
        if login:
            # Retain fixture history, but disable exactly the newly created login.
            with connection.get_connection() as owner:
                with owner.cursor() as cursor:
                    cursor.execute(sql.SQL('ALTER ROLE {} NOLOGIN').format(sql.Identifier(login['username'])))
                owner.commit()
            agent_api.decommission_agent(actor)
