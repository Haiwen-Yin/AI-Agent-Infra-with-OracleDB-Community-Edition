try:
    from shared.lib import knowledge_api
except ModuleNotFoundError:  # generated edition
    from lib import knowledge_api


def test_knowledge_scope_predicate_uses_authoritative_organization_facts():
    sql = knowledge_api.knowledge_access_predicate("e", ":principal_id").upper()
    assert "CX_KNOWLEDGE_ACCESS_POLICIES" in sql
    assert "CX_ORGANIZATION_MEMBERS" in sql
    assert "CX_ORGANIZATION_CLOSURE" in sql
    assert "ORGANIZATION_SUBTREE" in sql
    assert "ORGANIZATION_LEVEL" in sql
    assert "PRINCIPAL_PRIVATE" in sql
    assert "CX_AGENT_RELATIONSHIPS" in sql
    assert "PRIMARY_OWNER" in sql
    assert "KR.ENDED_AT" in sql
    assert "KH.STATUS='ACTIVE'" in sql
    assert "MO.STATUS='ACTIVE'" in sql
    assert "VISIBILITY IN ('PUBLIC','SHARED')" not in sql


def test_policy_validation_requires_correct_group_target(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_api, "execute", lambda sql, params: calls.append((sql, params)) or 1)
    result = knowledge_api.set_access_policy(
        "knowledge-1", "ORGANIZATION_SUBTREE", "admin",
        organization_id="finance", reason="Finance-only policy",
    )
    assert result["organization_id"] == "finance"
    assert len(calls) == 2


def test_policy_validation_rejects_missing_organization():
    try:
        knowledge_api.set_access_policy("knowledge-1", "ORGANIZATION_SUBTREE", "admin", reason="test")
    except ValueError as exc:
        assert "requires organization" in str(exc)
    else:
        raise AssertionError("organization scope must fail closed")


def test_agent_knowledge_context_resolves_single_line_org_chain_and_groups(monkeypatch):
    calls = []

    def query_one(sql, params):
        calls.append((sql, params))
        if "CX_AGENT_RELATIONSHIPS" in sql:
            return {"principal_id": "HP_OWNER", "responsible_group_id": "RG_ENGINEERING"}
        if "FROM CX_RESPONSIBLE_GROUPS" in sql:
            return {"group_id": "RG_ENGINEERING", "group_name": "研发", "security_domain_id": "SD_1", "member_role": "AGENT_RELATION"}
        return None

    def query(sql, params):
        calls.append((sql, params))
        if "CX_ORGANIZATION_CLOSURE" in sql:
            return [
                {"organization_id": "ORG_ROOT", "organization_name": "公司", "parent_id": None, "depth": 1},
                {"organization_id": "ORG_ENG", "organization_name": "研发", "parent_id": "ORG_ROOT", "depth": 0},
            ]
        if "CX_RESPONSIBLE_GROUP_MEMBERS" in sql:
            return []
        if "COLLAB_GROUP_MEMBERS" in sql:
            return [{"group_id": "CG_GRAPH", "group_name": "图工程组", "group_type": "TEAM", "sharing_policy": "RESTRICTED", "role": "MEMBER"}]
        return []

    monkeypatch.setattr(knowledge_api, "execute_query_one", query_one)
    monkeypatch.setattr(knowledge_api, "execute_query", query)
    context = knowledge_api.get_agent_knowledge_context("AG_1")
    assert [item["organization_id"] for item in context["organization_chain"]] == ["ORG_ROOT", "ORG_ENG"]
    assert context["organization_id"] == "ORG_ENG"
    assert context["responsible_groups"][0]["group_id"] == "RG_ENGINEERING"
    assert context["execution_groups"][0]["group_id"] == "CG_GRAPH"
    assert any("CX_ORGANIZATION_CLOSURE" in sql for sql, _ in calls)
    assert any("m.MEMBERSHIP_KIND='PRIMARY'" in sql for sql, _ in calls)


def test_agent_private_knowledge_policy_targets_agent_not_human_owner(monkeypatch):
    writes = []
    policies = []
    context = {
        "agent_id": "AG_1", "principal_id": "HP_OWNER", "organization_id": "ORG_ENG",
        "organization_chain": [], "responsible_groups": [], "execution_groups": [],
    }
    monkeypatch.setattr(knowledge_api, "execute", lambda sql, params: writes.append((sql, params)) or 1)
    monkeypatch.setattr(
        knowledge_api, "set_access_policy",
        lambda entity_id, scope, actor, **kwargs: policies.append((entity_id, scope, actor, kwargs)) or {},
    )
    result = knowledge_api.capture_agent_knowledge_context(
        "K_1", "AG_1", sharing_scope="PRINCIPAL_PRIVATE", context=context,
    )
    assert result["sharing_scope"] == "PRINCIPAL_PRIVATE"
    assert policies[0][2] == "AG_1"
    assert policies[0][3]["principal_id"] == "AG_1"


def test_organization_level_agent_knowledge_forwards_depth(monkeypatch):
    policies = []
    context = {
        "agent_id": "AG_1", "principal_id": "HP_OWNER", "organization_id": "ORG_ENG",
        "organization_chain": [], "responsible_groups": [], "execution_groups": [],
    }
    monkeypatch.setattr(knowledge_api, "execute", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        knowledge_api, "set_access_policy",
        lambda entity_id, scope, actor, **kwargs: policies.append(kwargs) or {},
    )
    knowledge_api.capture_agent_knowledge_context(
        "K_1", "AG_1", sharing_scope="ORGANIZATION_LEVEL", hierarchy_depth=2, context=context,
    )
    assert policies[0]["hierarchy_depth"] == 2
