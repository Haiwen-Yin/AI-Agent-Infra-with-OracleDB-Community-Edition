"""Human-approved fixed framework execution with durable exact bindings."""
import hashlib
import json
from pathlib import Path

from . import connection, identity_api, effective_capabilities, content_security
from . import continuity_work as work
from .agent_extension_contracts import row, canonical, digest, identifier, bounded_json, safe_key
from .isolated_framework_runtime import FRAMEWORK_VERSION
from .isolated_channel_runtime import verify_rootfs


def adapter_digest():
    return hashlib.sha256(Path(__file__).with_name('isolated_framework_worker.py').read_bytes()).hexdigest()


def binding(execution_id, *, tx=None):
    from .edition_features import AGENT_EXTENSIONS_ENABLED
    if not AGENT_EXTENSIONS_ENABLED:
        return None
    query = tx.query_one if tx else connection.execute_query_one
    return row(query('SELECT f.*,b.PROFILE_ID,b.PROFILE_VERSION,b.PERMISSION_VERSION,b.TARGET_ID FROM CX_FRAMEWORK_EXECUTIONS f JOIN CX_FRAMEWORK_BINDINGS b ON b.EXECUTION_ID=f.EXECUTION_ID WHERE f.EXECUTION_ID=:execution', {'execution': execution_id})) or None


def _authority(tx, actor, domain, agent_id):
    effective_capabilities.require(actor, graph='framework_adapter_execution', action='platform.manage', impact='EXECUTE')
    effective_capabilities.authorize(actor, 'agents.operate')
    principal = row(tx.query_one('SELECT PRINCIPAL_TYPE,STATUS,PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor FOR UPDATE', {'actor': actor}))
    if principal.get('principal_type') != 'HUMAN' or principal.get('status') != 'ACTIVE':
        raise PermissionError('framework execution requires an authorized Human')
    work._authorize(tx, actor, domain, write=True)
    if not identity_api._agent_visible_to(actor, agent_id):
        raise PermissionError('Agent is outside delegated scope')
    # The Human requester owns the execution's work-domain authorization.
    # Requiring the target Agent itself to hold a Work-space permission made
    # an approved, visible Agent unusable for the fixed-framework path.
    work._authorize(tx, actor, domain, write=False)
    agent = row(tx.query_one('SELECT STATUS,LLM_PROFILE_ID,DEPLOYMENT_TARGET_ID FROM CX_NATIVE_AGENTS WHERE AGENT_ID=:agent', {'agent': agent_id}))
    if agent.get('status') != 'ACTIVE':
        raise PermissionError('framework Agent is inactive')
    profile = row(tx.query_one('SELECT PROFILE_ID,VERSION,STATUS,HEALTH_STATE FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile', {'profile': agent.get('llm_profile_id')}))
    target = row(tx.query_one('SELECT TARGET_ID,TARGET_TYPE,STATUS,CONFIG_JSON FROM CX_DEPLOYMENT_TARGETS WHERE TARGET_ID=:target', {'target': agent.get('deployment_target_id')}))
    if profile.get('status') != 'ACTIVE' or profile.get('health_state') != 'HEALTHY':
        raise PermissionError('a healthy active Provider Profile is required')
    if target.get('status') != 'ACTIVE' or target.get('target_type') != 'LOCAL_LINUX_SANDBOX':
        raise PermissionError('a verified Linux sandbox target is required')
    config = json.loads(target.get('config_json') or '{}')
    rootfs = str(config.get('framework_rootfs') or '')
    if not rootfs or config.get('egress') or int(config.get('uid', 0)) < 1 or int(config.get('gid', 0)) < 1:
        raise PermissionError('the isolated framework image is not configured')
    return principal, profile, target, {**config, 'rootfs': rootfs}


def validate(tx, execution, receipt, *, verify_image=False):
    principal, profile, target, config = _authority(tx, receipt['actor_id'], receipt['security_domain_id'], execution['agent_id'])
    if (int(principal['permission_version']) != int(receipt['permission_version'])
            or profile['profile_id'] != receipt['profile_id'] or int(profile['version']) != int(receipt['profile_version'])
            or target['target_id'] != receipt['target_id'] or target['target_id'] != execution['target_id']
            or receipt['framework_key'] != 'langgraph' or receipt['framework_version'] != FRAMEWORK_VERSION
            or receipt['adapter_digest'] != adapter_digest()):
        raise PermissionError('framework execution authority or version changed')
    payload = json.loads(execution['input_json'])
    if set(payload) != {'messages', 'framework_dispatch'} or payload['framework_dispatch'] != {'framework': 'langgraph'} or digest(payload) != receipt['input_digest']:
        raise PermissionError('framework input binding changed')
    if verify_image and verify_rootfs(config['rootfs'], worker_name='isolated_framework_worker.py') != receipt['rootfs_digest']:
        raise PermissionError('framework rootfs binding changed')
    return config


def enqueue(actor, domain, agent_id, messages, idempotency_key, reason):
    safe_key(idempotency_key)
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000:
        raise ValueError('an execution reason is required')
    if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
        raise ValueError('between 1 and 100 messages are required')
    for message in messages:
        if not isinstance(message, dict) or set(message) != {'role', 'content'} or message['role'] not in {'system', 'user', 'assistant'} or not isinstance(message['content'], str):
            raise ValueError('framework messages must contain only a role and text')
    bounded_json(messages)
    content_security.inspect_messages(messages)
    payload = {'messages': messages, 'framework_dispatch': {'framework': 'langgraph'}}
    request_digest = digest({'domain': domain, 'agent': agent_id, 'payload': payload, 'reason': reason})
    def perform(tx):
        principal, profile, target, config = _authority(tx, actor, domain, agent_id)
        prior = row(tx.query_one('SELECT REQUEST_DIGEST,EXECUTION_ID FROM CX_FRAMEWORK_REQUESTS WHERE ACTOR_ID=:actor AND IDEMPOTENCY_KEY=:request_key', {'actor': actor, 'request_key': idempotency_key}))
        if prior:
            if prior['request_digest'] != request_digest:
                raise ValueError('framework idempotency key belongs to another input')
            receipt = binding(prior['execution_id'], tx=tx)
            execution = row(tx.query_one('SELECT * FROM CX_RUNTIME_EXECUTIONS WHERE EXECUTION_ID=:execution', {'execution': prior['execution_id']}))
            validate(tx, execution, receipt, verify_image=True)
            return {'execution_id': prior['execution_id'], 'status': execution['status'], 'replayed': True}
        rootfs_digest = verify_rootfs(config['rootfs'], worker_name='isolated_framework_worker.py')
        execution_id = identifier('FWX')
        tx.execute("INSERT INTO CX_RUNTIME_EXECUTIONS(EXECUTION_ID,AGENT_ID,TARGET_ID,ISOLATION_LEVEL,STATUS,INPUT_JSON,CONTEXT_DIGEST) VALUES(:execution,:agent,:target,'DEDICATED_CONTAINER','PENDING',:payload,:digest)", {'execution': execution_id, 'agent': agent_id, 'target': target['target_id'], 'payload': canonical(payload), 'digest': digest(payload)})
        tx.execute('INSERT INTO CX_FRAMEWORK_EXECUTIONS(EXECUTION_ID,ACTOR_ID,SECURITY_DOMAIN_ID,FRAMEWORK_KEY,FRAMEWORK_VERSION,ADAPTER_DIGEST,ROOTFS_DIGEST,INPUT_DIGEST) VALUES(:execution,:actor,:domain,\'langgraph\',:version,:adapter,:rootfs,:input_digest)', {'execution': execution_id, 'actor': actor, 'domain': domain, 'version': FRAMEWORK_VERSION, 'adapter': adapter_digest(), 'rootfs': rootfs_digest, 'input_digest': digest(payload)})
        tx.execute('INSERT INTO CX_FRAMEWORK_BINDINGS(EXECUTION_ID,PROFILE_ID,PROFILE_VERSION,PERMISSION_VERSION,TARGET_ID) VALUES(:execution,:profile,:profile_version,:permission_version,:target)', {'execution': execution_id, 'profile': profile['profile_id'], 'profile_version': int(profile['version']), 'permission_version': int(principal['permission_version']), 'target': target['target_id']})
        tx.execute('INSERT INTO CX_FRAMEWORK_REQUESTS(ACTOR_ID,IDEMPOTENCY_KEY,REQUEST_DIGEST,EXECUTION_ID) VALUES(:actor,:request_key,:digest,:execution)', {'actor': actor, 'request_key': idempotency_key, 'digest': request_digest, 'execution': execution_id})
        identity_api._audit_tx(tx, actor, 'FRAMEWORK_EXECUTION_QUEUED', 'RUNTIME_EXECUTION', execution_id, 'ALLOW', reason)
        return {'execution_id': execution_id, 'agent_id': agent_id, 'status': 'PENDING', 'replayed': False}
    return connection.execute_transaction_callback(perform)


def complete(tx, execution, output):
    receipt = binding(execution['execution_id'], tx=tx)
    validate(tx, execution, receipt)
    observation = getattr(execution['_isolated_worker'], 'observation', None)
    if observation != {'framework': 'langgraph', 'framework_version': FRAMEWORK_VERSION, 'steps': ['prepare', 'model', 'finalize']}:
        raise PermissionError('framework completion was not observed')
    evidence = execution['_isolated_worker'].evidence()
    if evidence['rootfs_digest'] != receipt['rootfs_digest']:
        raise PermissionError('framework isolation identity changed')
    value = {**observation, 'rootfs_digest': receipt['rootfs_digest'], 'adapter_digest': receipt['adapter_digest'],
             'input_digest': receipt['input_digest'], 'output_digest': digest(output), 'isolation_verified': True}
    tx.execute('UPDATE CX_FRAMEWORK_EXECUTIONS SET OBSERVATION_JSON=:observation,OBSERVATION_DIGEST=:digest WHERE EXECUTION_ID=:execution', {'observation': canonical(value), 'digest': digest(value), 'execution': execution['execution_id']})
    identity_api._audit_tx(tx, receipt['actor_id'], 'FRAMEWORK_EXECUTION_COMPLETED', 'RUNTIME_EXECUTION', execution['execution_id'], 'ALLOW', 'Exact isolated framework receipt')


def require_reader(actor, execution, *, tx=None):
    receipt = binding(execution['execution_id'], tx=tx)
    if not receipt:
        return
    if receipt['actor_id'] != actor:
        raise PermissionError('framework result is private to its requester')
    def perform(transaction):
        validate(transaction, execution, receipt)
    if tx:
        perform(tx)
    else:
        connection.execute_transaction_callback(perform)
