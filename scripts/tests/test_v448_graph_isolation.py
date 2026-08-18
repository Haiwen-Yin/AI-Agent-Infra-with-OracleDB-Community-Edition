from pathlib import Path


def test_graph_neighbors_and_paths_inherit_caller_authorization():
    root = Path(__file__).resolve().parents[1]
    graph = (root / "lib" / "graph_api.py").read_text(encoding="utf-8")
    relational = graph.split("def _relational_neighbors", 1)[1].split("def get_neighbors", 1)[0]
    assert "_target_visibility_clause(principal_id)" in relational
    assert '_target_visibility_clause(principal_id, "source")' in relational
    reachable = graph.split("def get_reachable", 1)[1].split("def get_shortest_path", 1)[0]
    assert "principal_id=principal_id" in reachable
    shortest = graph.split("def get_shortest_path", 1)[1].split("def find_similar_entities", 1)[0]
    assert "principal_id=principal_id" in shortest
    context = graph.split("def get_entity_context", 1)[1]
    assert "principal_id=principal_id" in context


def test_graph_http_mcp_and_unified_search_pass_principal_identity():
    root = Path(__file__).resolve().parents[1]
    server = (root / "visualization" / "server.py").read_text(encoding="utf-8")
    assert "graph_api.get_neighbors(entity_id, principal_id=self._graph_actor())" in server
    assert "graph_api.get_entity_context(" in server
    assert "principal_id=self._graph_actor()" in server
    search = (root / "lib" / "search_api.py").read_text(encoding="utf-8")
    graph_search = search.split('elif strategy == "graph"', 1)[1].split('elif strategy == "hybrid"', 1)[0]
    assert "principal_id=principal_id" in graph_search
    mcp = (root / "lib" / "mcp_server.py").read_text(encoding="utf-8")
    assert "principal_id=authenticated_agent" in mcp.split('elif name == "graph_neighbors"', 1)[1]
