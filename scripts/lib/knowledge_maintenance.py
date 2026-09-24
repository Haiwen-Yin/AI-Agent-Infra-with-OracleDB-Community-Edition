"""Audited, optimistic updates; never rewrite historical migration checksums."""
import hashlib
import json

from . import connection, identity_api


def digest(row):
    return hashlib.sha256(json.dumps(
        {key: str(row.get(key) or '') for key in ('entity_id', 'title', 'summary', 'content')},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def repair(actor, replacements, *, grant_agent_read=False, reason):
    """Apply an operator-reviewed exact-ID/content-digest plan in one transaction."""
    identity_api._require(actor, 'platform.manage')
    if grant_agent_read:
        identity_api._require(actor, 'users.roles.manage.all')
    if not reason.strip() or not isinstance(replacements, list) or len(replacements) > 50:
        raise ValueError('A bounded reviewed plan and reason are required')
    if len({str(item['entity_id']) for item in replacements}) != len(replacements):
        raise ValueError('Duplicate Knowledge IDs')

    def work(tx):
        updated = []
        for item in replacements:
            row = identity_api._row(tx.query_one(
                "SELECT ENTITY_ID,TITLE,SUMMARY,CONTENT FROM ENTITIES "
                "WHERE ENTITY_ID=:entity AND ENTITY_TYPE='KNOWLEDGE' FOR UPDATE",
                {'entity': item['entity_id']}))
            if not row or digest(row) != item['expected_digest']:
                raise ValueError('Knowledge changed since review')
            from . import content_security
            content_security.enforce(item['content'], 'KNOWLEDGE')
            tx.execute("UPDATE ENTITIES SET TITLE=:title,SUMMARY=:summary,CONTENT=:content,"
                       "UPDATED_AT=CURRENT_TIMESTAMP WHERE ENTITY_ID=:entity AND ENTITY_TYPE='KNOWLEDGE'",
                       {'entity': item['entity_id'], 'title': item['title'],
                        'summary': item['summary'], 'content': item['content']})
            identity_api._audit_tx(tx, actor, 'PRODUCT_KNOWLEDGE_REFRESH', 'KNOWLEDGE',
                                   str(item['entity_id']), 'ALLOW', reason)
            updated.append(str(item['entity_id']))
        role_changed = False
        if grant_agent_read:
            role = identity_api._row(tx.query_one(
                "SELECT PERMISSIONS_JSON FROM CX_ROLE_TEMPLATES WHERE ROLE_CODE='AGENT' FOR UPDATE", {}))
            if not role:
                raise ValueError('AGENT role is unavailable')
            permissions = json.loads(str(role['permissions_json']))
            if not isinstance(permissions, list) or any(not isinstance(value, str) for value in permissions):
                raise ValueError('AGENT permissions are invalid')
            if 'knowledge.read' not in permissions:
                permissions.append('knowledge.read')
                tx.execute("UPDATE CX_ROLE_TEMPLATES SET PERMISSIONS_JSON=:permissions,"
                           "VERSION=VERSION+1,UPDATED_AT=CURRENT_TIMESTAMP WHERE ROLE_CODE='AGENT'",
                           {'permissions': json.dumps(permissions)})
                identity_api._audit_tx(tx, actor, 'AGENT_KNOWLEDGE_READ_ENABLE', 'ROLE', 'AGENT', 'ALLOW', reason)
                role_changed = True
        return {'updated_ids': updated, 'role_changed': role_changed}
    return connection.execute_transaction_callback(work)
