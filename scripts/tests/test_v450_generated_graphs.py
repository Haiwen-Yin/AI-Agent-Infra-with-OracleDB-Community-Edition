"""Reproducible generated graph shapes and minimized invalid retry cases."""
from copy import deepcopy
import random
import pytest
from lib.graph_compiler import compile_definition
from lib.graph_compiler import _cycle_nodes


def graph(seed):
    rng = random.Random(seed)
    width = rng.randint(2, 10)
    names = ['start'] + ['work-' + str(i) for i in range(width)] + ['end']
    nodes = [{'node_key': name, 'node_type': 'START' if name == 'start' else 'END' if name == 'end' else 'AGENT'} for name in names]
    edges = [{'edge_id': 'edge-' + str(i), 'source_node_key': a, 'target_node_key': b}
             for i, (a, b) in enumerate(zip(names, names[1:]))]
    return dict(schema_version='1.0', graph_version_id='generated-' + str(seed), nodes=nodes, edges=edges, budget={})


@pytest.mark.parametrize('seed', range(32))
def test_generated_reachability_cycles_and_permutation(seed):
    value = graph(seed)
    accepted = compile_definition(value)
    assert accepted['valid'], (seed, accepted['diagnostics'])
    shuffled = deepcopy(value)
    rng = random.Random(seed + 20260927)
    rng.shuffle(shuffled['nodes'])
    rng.shuffle(shuffled['edges'])
    assert compile_definition(shuffled)['plan_digest'] == accepted['plan_digest']
    value['edges'].append(dict(edge_id='cycle', source_node_key='work-0', target_node_key='work-0', edge_kind='CYCLE'))
    rejected = compile_definition(value)
    assert not rejected['valid']
    assert 'CYCLE_UNBOUNDED' in {d['code'] for d in rejected['diagnostics']}, seed
    value['budget'] = {'max_iterations': 3}
    assert compile_definition(value)['valid'], seed
    value['nodes'].append(dict(node_key='unreachable', node_type='AGENT'))
    assert 'NODE_UNREACHABLE' in {d['code'] for d in compile_definition(value)['diagnostics']}, seed


@pytest.mark.parametrize('count', ['two', None, True, 0, -1, 1.5, float('nan'), float('inf'), [], {}])
def test_invalid_retry_count_is_diagnostic_not_server_exception(count):
    value = graph(0)
    value['nodes'][1].update(side_effect_class='NON_IDEMPOTENT', config={'retry_policy': {'max_attempts': count}})
    result = compile_definition(value)
    assert not result['valid']
    assert 'RETRY_POLICY_INVALID' in {d['code'] for d in result['diagnostics']}


@pytest.mark.parametrize('policy', ['bad', ['bad'], 1, False, 0, []])
def test_retry_policy_requires_object(policy):
    value = graph(0)
    value['nodes'][1]['config'] = {'retry_policy': policy}
    result = compile_definition(value)
    assert not result['valid']
    assert 'RETRY_POLICY_INVALID' in {d['code'] for d in result['diagnostics']}


def test_non_idempotent_retry_requires_explicit_resolution():
    value = graph(0)
    value['nodes'][1].update(side_effect_class='NON_IDEMPOTENT', config={'retry_policy': {'max_attempts': 2}})
    assert 'NON_IDEMPOTENT_RETRY_UNSAFE' in {d['code'] for d in compile_definition(value)['diagnostics']}
    value['nodes'][1]['config']['retry_policy']['confirmation_required'] = True
    assert compile_definition(value)['valid']


def test_cycle_detection_is_iterative_and_reports_all_cycle_members():
    long_graph = {str(i): [str(i + 1)] for i in range(5000)}
    assert _cycle_nodes(long_graph) == set()
    assert _cycle_nodes({'a': ['b', 'c'], 'b': ['a'], 'c': ['b']}) == {'a', 'b', 'c'}


@pytest.mark.parametrize('seed', range(32))
def test_cycle_members_match_independent_reachability(seed):
    rng = random.Random(seed)
    names = [str(i) for i in range(12)]
    adjacency = {a: [b for b in names if rng.random() < .12] for a in names}
    expected = set()
    for start in names:
        pending = list(adjacency[start])
        seen = set()
        while pending:
            node = pending.pop()
            if node == start:
                expected.add(start)
                break
            if node not in seen:
                seen.add(node)
                pending.extend(adjacency[node])
    assert _cycle_nodes(adjacency) == expected, seed


@pytest.mark.parametrize('value', [True, '2', -1, 0, float('nan'), float('inf'), 10**400])
def test_timeouts_and_budgets_require_finite_positive_numbers(value):
    definition = graph(1)
    definition['edges'][0]['config'] = {'timeout_seconds': value}
    definition['budget'] = {'max_calls': value}
    definition['nodes'][1]['budget'] = {'max_iterations': value}
    codes = [item['code'] for item in compile_definition(definition)['diagnostics']]
    assert 'TIMEOUT_INVALID' in codes
    assert codes.count('BUDGET_INVALID') == 2


def join_graph(seed):
    rng = random.Random(seed)
    width = rng.randint(3, 8)
    value = graph(seed)
    value['nodes'] = [{'node_key': 'start', 'node_type': 'START'},
                      {'node_key': 'end', 'node_type': 'END'}]
    value['edges'] = []
    for i in range(width):
        key = 'branch-' + str(i)
        value['nodes'].append({'node_key': key, 'node_type': 'AGENT'})
        value['edges'].extend([
            {'edge_id': 'out-' + str(i), 'source_node_key': 'start', 'target_node_key': key},
            {'edge_id': 'in-' + str(i), 'source_node_key': key, 'target_node_key': 'end',
             'join_key': 'join', 'config': {'join_strategy': 'N_OF_M'}}])
    value['edges'][1]['config']['required_count'] = 2
    return value


@pytest.mark.parametrize('seed', range(16))
def test_generated_join_has_one_threshold_independent_of_branch_order(seed):
    value = join_graph(seed)
    result = compile_definition(value)
    assert result['valid'], result['diagnostics']
    assert result['plan']['join_specs']['end']['required_count'] == 2
    random.Random(seed).shuffle(value['edges'])
    assert compile_definition(value)['plan_digest'] == result['plan_digest']


@pytest.mark.parametrize('value,code', [(1, 'JOIN_REQUIRED_COUNT_CONFLICT'),
                                      (True, 'JOIN_REQUIRED_COUNT_INVALID'),
                                      (100, 'JOIN_REQUIRED_COUNT_INVALID'),
                                      ('2', 'JOIN_REQUIRED_COUNT_INVALID')])
def test_join_validates_every_incoming_threshold_and_alias(value, code):
    definition = join_graph(3)
    definition['edges'][3]['config']['n'] = value
    assert code in {d['code'] for d in compile_definition(definition)['diagnostics']}


@pytest.mark.parametrize('seed', range(32))
def test_generated_schema_exit_extension_permission_and_topology_mutations(seed):
    value = graph(seed)
    rng = random.Random(seed)
    edge_index = rng.randrange(len(value['edges']))
    edge = value['edges'][edge_index]
    nodes = {node['node_key']: node for node in value['nodes']}
    source, target = nodes[edge['source_node_key']], nodes[edge['target_node_key']]
    kind = rng.choice(['string', 'number', 'boolean'])
    field = 'value-' + str(seed)
    source['output_schema'] = {'type': 'object', 'properties': {field: {'type': kind}}}
    target['input_schema'] = {'type': 'object', 'required': [field], 'properties': {field: {'type': kind}}}
    assert compile_definition(value)['valid']
    invalid = deepcopy(value)
    next(node for node in invalid['nodes'] if node['node_key'] == target['node_key'])['input_schema']['properties'][field]['type'] = 'array'
    assert 'SCHEMA_TYPE_MISMATCH' in {d['code'] for d in compile_definition(invalid)['diagnostics']}
    no_exit = deepcopy(value)
    no_exit['nodes'][-1]['node_type'] = 'AGENT'
    assert 'EXIT_MISSING' in {d['code'] for d in compile_definition(no_exit)['diagnostics']}
    extension = deepcopy(value)
    extension['nodes'][1]['type_version'] = 'unregistered-' + str(seed)
    assert 'NODE_TYPE_UNAVAILABLE' in {d['code'] for d in compile_definition(extension)['diagnostics']}
    denied = deepcopy(value)
    denied['edges'][edge_index].update(decision_type='EXPRESSION',
        condition={'op': 'ref', 'path': rng.choice(['environment.secret', 'credentials.token', 'filesystem.private'])})
    assert any(d['code'] in {'EXPRESSION_REF_SCOPE', 'EXPRESSION_FORBIDDEN'}
               for d in compile_definition(denied)['diagnostics'])
    # Apply an additive topology change that preserves the data contract.
    dynamic = deepcopy(value)
    dynamic['nodes'].append({'node_key': 'inserted', 'node_type': 'AGENT',
                            'input_schema': deepcopy(target['input_schema']),
                            'output_schema': deepcopy(source['output_schema'])})
    dynamic['edges'][edge_index]['target_node_key'] = 'inserted'
    dynamic['edges'].append({'edge_id': 'inserted-edge', 'source_node_key': 'inserted',
                             'target_node_key': target['node_key']})
    changed = compile_definition(dynamic)
    assert changed['valid'], (seed, changed['diagnostics'])
    assert changed['plan_digest'] != compile_definition(value)['plan_digest']
