"""Versioned Memory without a legacy entity remains visible in the graph."""
import ast
from pathlib import Path
from types import SimpleNamespace


def test_native_family_ids_never_enter_legacy_entity_tag_queries():
    source=Path(__file__).resolve().parents[1]/'visualization/server.py'
    tree=ast.parse(source.read_text())
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef)
              and node.name in {'_memory_to_vis','_get_tags_for_entities'}]
    items=[dict(entity_id='MF-native',family_id='MF-native',version_id='MV-native',title='Native'),
           dict(entity_id='42',legacy_entity_id='42',family_id='MF-legacy',version_id='MV-legacy',title='Adopted'),
           dict(entity_id=43,title='Legacy')]
    queries=[]
    def query(sql,params):
        queries.append((sql,params))
        if 'entity_tags' in sql:
            assert list(params.values())==['42',43]
            assert 'MF-native' not in sql and '42' not in sql
            return [dict(entity_id=42,tag_name='adopted-tag'),dict(entity_id=43,tag_name='legacy-tag')]
        assert 'CX_MEMORY_RELATIONS' in sql
        return []
    scope={'connection':SimpleNamespace(execute_query=query),
           'memory_api':SimpleNamespace(search_memories=lambda **kwargs:items)}
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),scope)
    graph=scope['_memory_to_vis']()
    assert [(node['id'],node['tags']) for node in graph['nodes']]==[
        ('MV-native',[]),('MV-legacy',['adopted-tag']),(43,['legacy-tag'])]
    assert len(queries)==2
