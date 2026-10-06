"""Durable shared Portal/Channel answer-quality cases and results."""
import time

from . import answer_planning, connection, effective_capabilities, identity_api, knowledge_grounding
from .agent_extension_contracts import bounded_json, canonical, digest, identifier, row

ENTRY_KINDS = frozenset({'PORTAL', 'CHANNEL'})
EXPECTED_MODES = frozenset({'MATCHED', 'PARTIAL_MATCH', 'NO_MATCH', 'AMBIGUOUS'})
OBSERVED_MODES = frozenset({'KNOWLEDGE_GROUNDED', 'MIXED_SOURCES', 'MODEL_SUPPLEMENT', 'KNOWLEDGE_EXTRACTS', 'CLARIFICATION_REQUIRED', 'INSUFFICIENT_KNOWLEDGE'})


def _require_owner(actor):
    return effective_capabilities.authorize(actor, 'platform.manage')


def register_case(actor, case_id, query_text, expected_mode, expected_entity_ids, *, reason='Approved answer-quality case'):
    _require_owner(actor)
    if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 128:
        raise ValueError('case_id is required')
    if not isinstance(query_text, str) or not 1 <= len(query_text.strip()) <= 2000:
        raise ValueError('query_text is required')
    expected_mode = str(expected_mode or '').upper()
    if expected_mode not in EXPECTED_MODES:
        raise ValueError('unsupported expected retrieval mode')
    if not isinstance(expected_entity_ids, list) or len(expected_entity_ids) > 32 or any(not isinstance(item, str) or not item.strip() for item in expected_entity_ids):
        raise ValueError('expected_entity_ids must be a bounded string list')
    value = {'case_id': case_id.strip(), 'query_text': query_text.strip(), 'expected_mode': expected_mode,
             'expected_entity_ids': list(dict.fromkeys(expected_entity_ids))}
    bounded_json(value, maximum=128 * 1024)
    case_digest = digest(value)
    def perform(tx):
        previous = row(tx.query_one('SELECT VERSION,CASE_DIGEST,STATUS FROM CX_ANSWER_EVAL_CASES WHERE CASE_ID=:case_id ORDER BY VERSION DESC', {'case_id': value['case_id']}))
        version = int(previous['version']) + 1 if previous else 1
        if previous and previous['case_digest'] == case_digest and previous['status'] == 'ACTIVE':
            return {'case_id': value['case_id'], 'version': int(previous['version']), 'replayed': True, 'case_digest': case_digest}
        if previous and previous['status'] == 'ACTIVE':
            tx.execute('UPDATE CX_ANSWER_EVAL_CASES SET STATUS=\'RETIRED\' WHERE CASE_ID=:case_id AND VERSION=:version', {'case_id': value['case_id'], 'version': int(previous['version'])})
        tx.execute('INSERT INTO CX_ANSWER_EVAL_CASES(CASE_ID,VERSION,CASE_NAME,QUERY_TEXT,EXPECTED_MODE,EXPECTED_ENTITIES_JSON,STATUS,APPROVED_BY,CASE_DIGEST) VALUES(:case_id,:version,:name,:query,:expected_mode,:entities,\'ACTIVE\',:actor,:digest)', {'case_id': value['case_id'], 'version': version, 'name': value['case_id'], 'query': value['query_text'], 'expected_mode': expected_mode, 'entities': canonical(value['expected_entity_ids']), 'actor': actor, 'digest': case_digest})
        identity_api._audit_tx(tx, actor, 'ANSWER_EVAL_CASE_REGISTERED', 'ANSWER_EVAL_CASE', value['case_id'], 'ALLOW', reason)
        return {'case_id': value['case_id'], 'version': version, 'replayed': False, 'case_digest': case_digest}
    return connection.execute_transaction_callback(perform)


def list_cases(actor, *, include_retired=False, limit=100):
    _require_owner(actor)
    if not 1 <= int(limit) <= 100:
        raise ValueError('limit is out of range')
    status = '' if include_retired else " AND STATUS='ACTIVE'"
    return [row(item) for item in connection.execute_query('SELECT CASE_ID,VERSION,CASE_NAME,QUERY_TEXT,EXPECTED_MODE,EXPECTED_ENTITIES_JSON,STATUS,CASE_DIGEST,CREATED_AT FROM CX_ANSWER_EVAL_CASES WHERE 1=1' + status + ' ORDER BY CREATED_AT DESC' + identity_api._limit_clause('limit'), {'limit': int(limit)})]


def record_result(actor, case_id, case_version, profile_id, profile_version, entry_kind, observed_mode, passed, latency_ms, policy_digest, detail):
    _require_owner(actor)
    if entry_kind not in ENTRY_KINDS or observed_mode not in OBSERVED_MODES:
        raise ValueError('unsupported answer evaluation entry')
    if type(passed) is not bool or not isinstance(latency_ms, int) or latency_ms < 0 or latency_ms > 3600000:
        raise ValueError('invalid answer evaluation timing/result')
    bounded_json(detail, maximum=128 * 1024)
    result_value = {'case_id': case_id, 'case_version': int(case_version), 'profile_id': profile_id, 'profile_version': int(profile_version), 'entry_kind': entry_kind, 'observed_mode': observed_mode, 'passed': passed, 'latency_ms': latency_ms, 'policy_digest': str(policy_digest), 'detail': detail}
    result_digest = digest(result_value)
    result_id = identifier('AER')
    def perform(tx):
        case = row(tx.query_one('SELECT STATUS FROM CX_ANSWER_EVAL_CASES WHERE CASE_ID=:case_id AND VERSION=:version', {'case_id': case_id, 'version': int(case_version)}))
        profile = row(tx.query_one('SELECT STATUS,VERSION FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile', {'profile': profile_id}))
        if not case or case['status'] != 'ACTIVE' or not profile or profile['status'] != 'ACTIVE' or int(profile['version']) != int(profile_version):
            raise PermissionError('answer evaluation case or Provider Profile is stale')
        tx.execute('INSERT INTO CX_ANSWER_EVAL_RESULTS(RESULT_ID,CASE_ID,CASE_VERSION,PROFILE_ID,PROFILE_VERSION,ENTRY_KIND,ACTOR_ID,OBSERVED_MODE,PASSED,LATENCY_MS,POLICY_DIGEST,RESULT_DIGEST,DETAIL_JSON) VALUES(:result,:case_id,:version,:profile,:profile_version,:entry,:actor,:observed_mode,:passed,:latency,:policy,:digest,:detail)', {'result': result_id, 'case_id': case_id, 'version': int(case_version), 'profile': profile_id, 'profile_version': int(profile_version), 'entry': entry_kind, 'actor': actor, 'observed_mode': observed_mode, 'passed': 1 if passed else 0, 'latency': latency_ms, 'policy': str(policy_digest)[:64], 'digest': result_digest, 'detail': canonical(detail)})
        identity_api._audit_tx(tx, actor, 'ANSWER_EVAL_RESULT_RECORDED', 'ANSWER_EVAL_RESULT', result_id, 'ALLOW', entry_kind)
        return {'result_id': result_id, 'passed': passed, 'result_digest': result_digest}
    return connection.execute_transaction_callback(perform)


def run_shared_case(actor, case_id, case_version, agent_id, profile_id, configured, *, entry_kind='PORTAL'):
    """Run the same retrieval/policy preparation used by Portal and Channel."""
    _require_owner(actor)
    if entry_kind not in ENTRY_KINDS:
        raise ValueError('entry_kind is invalid')
    case = next((item for item in list_cases(actor, include_retired=True) if item['case_id'] == case_id and int(item['version']) == int(case_version)), None)
    if not case:
        raise ValueError('answer evaluation case is unavailable')
    # Evaluation evidence is bound to the exact Provider Profile revision that
    # the selected Agent uses.  A caller supplied profile id or a hard-coded
    # version must never make a result appear current after a profile update.
    profile = row(connection.execute_query_one(
        'SELECT PROFILE_ID,VERSION,STATUS,HEALTH_STATE FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile',
        {'profile': profile_id},
    ))
    agent = row(connection.execute_query_one(
        'SELECT AGENT_ID,LLM_PROFILE_ID,STATUS FROM CX_NATIVE_AGENTS WHERE AGENT_ID=:agent',
        {'agent': agent_id},
    ))
    if not profile or profile.get('status') != 'ACTIVE' or profile.get('health_state') != 'HEALTHY':
        raise PermissionError('answer evaluation requires a healthy active Provider Profile')
    if not agent or agent.get('status') != 'ACTIVE' or agent.get('llm_profile_id') != profile_id:
        raise PermissionError('answer evaluation Agent/Profile binding is stale')
    profile_version = int(profile.get('version') or 0)
    if profile_version < 1:
        raise ValueError('Provider Profile version is invalid')
    started = time.monotonic()
    retrieval = answer_planning.retrieve(actor, agent_id, case['query_text'])
    prepared = answer_planning.prepare(case['query_text'], profile_id, configured, retrieval)
    expected_entities = set(__import__('json').loads(case['expected_entities_json'] or '[]'))
    observed_entities = {item.get('entity_id') for item in retrieval['items']}
    passed = retrieval['status'] == case['expected_mode'] and expected_entities.issubset(observed_entities)
    policy_digest = digest(configured)
    result = record_result(actor, case_id, case_version, profile_id, profile_version, entry_kind, prepared['answer_source'], passed, max(0, round((time.monotonic() - started) * 1000)), policy_digest, {'retrieval_status': retrieval['status'], 'retrieval_mode': retrieval.get('retrieval_mode'), 'citations': prepared['citations'], 'missing_parts': retrieval.get('missing_parts', [])})
    return {'case': case, 'retrieval': retrieval, 'prepared': {key: value for key, value in prepared.items() if key != 'messages'}, 'result': result}
