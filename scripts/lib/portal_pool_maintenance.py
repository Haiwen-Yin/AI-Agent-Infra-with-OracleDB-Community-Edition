"""Explicit administrator repair of legacy, idle, locally managed Portal Agents."""
from . import connection, identity_api


def adopt_idle_agents(actor, agent_ids, reason):
    identity_api._require(actor, 'platform.manage')
    identity_api._require(actor, 'users.roles.manage.all')
    if (not isinstance(agent_ids, list) or not 1 <= len(agent_ids) <= 50
            or any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in agent_ids)
            or len(set(agent_ids)) != len(agent_ids) or len(str(reason).strip()) < 3):
        raise ValueError('Explicit, unique Agent IDs and a repair reason are required')

    def work(tx):
        repaired = []
        for agent_id in sorted(agent_ids):
            row = identity_api._row(tx.query_one(
                'SELECT AGENT_ID,AGENT_NAME,AGENT_TYPE,STATUS,CURRENT_USER_ID,PORTAL_NODE_ID '
                'FROM AGENT_REGISTRY WHERE AGENT_ID=:agent FOR UPDATE', {'agent': agent_id}))
            if (not row or row['agent_type'] != 'PORTAL_MANAGED' or row['status'] != 'POOL'
                    or row.get('current_user_id') or row.get('portal_node_id')):
                raise ValueError('Only idle local Portal-managed Agents can be adopted')
            registration = identity_api._row(tx.query_one(
                'SELECT STATUS FROM AGENT_REGISTRATIONS WHERE AGENT_ID=:agent FOR UPDATE', {'agent': agent_id}))
            if not registration or registration['status'] != 'ACTIVE':
                raise ValueError('An active managed registration is required')
            principal = identity_api._row(tx.query_one(
                'SELECT PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:agent FOR UPDATE',
                {'agent': agent_id}))
            if principal:
                if principal['principal_type'] != 'AGENT' or principal['status'] != 'ACTIVE':
                    raise ValueError('Existing disabled or conflicting identities cannot be adopted')
                continue
            tx.execute('INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID,PRINCIPAL_TYPE,DISPLAY_NAME,STATUS,PERMISSION_VERSION) '
                       "VALUES (:agent,'AGENT',:display_name,'ACTIVE',1)",
                       {'agent': agent_id, 'display_name': row.get('agent_name') or agent_id})
            identity_api._audit_tx(tx, actor, 'PORTAL_POOL_IDENTITY_ADOPT', 'AGENT', agent_id, 'ALLOW', reason)
            repaired.append(agent_id)
        return {'adopted': repaired, 'checked': len(agent_ids)}
    return connection.execute_transaction_callback(work)
