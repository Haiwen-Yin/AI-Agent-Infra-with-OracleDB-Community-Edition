from pathlib import Path

import pytest
import migration_runner
import live_db_validator
try:
    from shared.lib import agent_registration, compliance_api, embedding_governance, identity_api, model_usage_api, monitor_api
except ModuleNotFoundError:  # generated edition
    from lib import agent_registration, compliance_api, embedding_governance, identity_api, model_usage_api, monitor_api


ROOT = Path(__file__).resolve().parents[2]
GENERATED = (ROOT / "build-manifest.json").is_file()
if GENERATED:
    _manifest = __import__("json").loads((ROOT / "build-manifest.json").read_text(encoding="utf-8"))
    GENERATED_DATABASE = str((_manifest.get("database") or {}).get("key") or "")
    WEB_APP_SOURCE = ROOT / "scripts" / "web_app.py"
    LIB_SOURCE = ROOT / "scripts" / "lib"
    RUNNER_SOURCE = ROOT / "scripts" / "migration_runner.py"
    DEPLOY_SOURCE = ROOT / "scripts" / "deploy"
else:
    GENERATED_DATABASE = ""
    WEB_APP_SOURCE = ROOT / "shared" / "web_app.py"
    LIB_SOURCE = ROOT / "shared" / "lib"
    RUNNER_SOURCE = ROOT / "migration_runner.py"
    DEPLOY_SOURCE = None


@pytest.mark.skipif(GENERATED, reason="cross-adapter script selection is a unified-source gate")
def test_v410_scripts_are_selected_for_all_adapters():
    for database in ("oracle", "pg", "yashandb"):
        names = migration_runner._v410_script_names(database, ROOT / "config.json", "enterprise")
        assert names[-11:] == [
            "55_v4_4_10_model_usage_wallboard.sql",
            "56_v4_4_10_runtime_repair.sql",
            "57_v4_4_10_complete_model_governance.sql",
            "58_v4_4_10_knowledge_scope.sql",
            "59_v4_4_10_knowledge_graph_context.sql",
            "60_v4_4_10_organization_approval_closure.sql",
            "61_v4_4_10_external_embedding_authorization.sql",
            "62_v4_4_10_agent_embedding_contract.sql",
            "63_v4_4_10_external_agent_gateway_grants.sql",
            "64_v4_4_10_external_agent_context_repair.sql",
            "65_v4_4_10_external_agent_domain_context.sql",
        ]
        assert (ROOT / "adapters" / database / "deploy" / names[-1]).is_file()


def test_migration_runner_imports_the_v410_static_validator():
    assert migration_runner.validate_v410_static_contract is live_db_validator.validate_v410_static_contract


def test_v410_preflight_includes_postgres_security_repair_overlays():
    source = RUNNER_SOURCE.read_text(encoding="utf-8")
    block = source.split('elif MIGRATION_VERSION == "4.4.10":', 1)[1].split('passed = bool(identity)', 1)[0]
    assert 'if database == "pg":' in block
    assert '51_v4_4_9_identity_boundary_repair.sql' in block
    assert '53_v4_4_9_pg_runtime_boundary.sql' in block


@pytest.mark.skipif(GENERATED, reason="cross-adapter identity implementation is a unified-source gate")
def test_external_enrollment_provisions_identity_and_uses_request_scoped_context():
    identity_source = (ROOT / "shared" / "lib" / "identity_api.py").read_text(encoding="utf-8")
    assert "ensure_external_agent_identity" in identity_source
    for database in ("oracle", "pg", "yashandb"):
        agent_source = (ROOT / "adapters" / database / "agent_api.py").read_text(encoding="utf-8")
        connection_source = (ROOT / "adapters" / database / "connection.py").read_text(encoding="utf-8")
        assert "def ensure_external_agent_identity" in agent_source
        assert "ContextVar" in connection_source
        assert "threading.local()" not in connection_source


@pytest.mark.skipif(GENERATED and GENERATED_DATABASE != "pg", reason="PostgreSQL package contract")
def test_pg_gateway_context_repair_is_agent_scoped():
    deploy = DEPLOY_SOURCE if GENERATED else ROOT / "adapters" / "pg" / "deploy"
    sql = (deploy / "64_v4_4_10_external_agent_context_repair.sql").read_text(encoding="utf-8").upper()
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "AGENT_ID = PUBLIC.CURRENT_AGENT_IDENTITY()" in sql
    assert "PRINCIPAL_ID = PUBLIC.CURRENT_AGENT_IDENTITY()" in sql


def test_gateway_token_can_request_every_scope_used_by_external_agent_routes():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    token_route = source.split('def gateway_token(', 1)[1].split('@app.get("/api/gateway/database-endpoint")', 1)[0]
    for scope in (
        "channels.read", "channels.write", "barriers.arrive", "actions.propose",
        "events.read", "compliance.evidence", "compliance.remediation",
        "embedding.probe", "embedding.generate", "database.endpoint", "skills.read",
        "memory.propose", "knowledge.read", "knowledge.write",
    ):
        assert f'"{scope}"' in token_route


def test_external_agent_memory_and_knowledge_routes_are_governed():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    assert '@app.post("/api/gateway/channels/{channel_id}/memory-candidates")' in source
    assert 'request, "memory.propose"' in source
    assert 'identity_api.propose_memory_candidate(' in source
    assert '@app.post("/api/gateway/knowledge")' in source
    assert '@app.get("/api/gateway/knowledge/{entity_id}")' in source
    assert 'request, "knowledge.write"' in source
    assert 'request, "knowledge.read"' in source
    assert 'scope == "PUBLIC_COMPANY"' in source
    assert "requires Human publication approval" in source


def test_external_agent_event_stream_encodes_database_native_values_before_streaming():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    route = source.split("def gateway_event_stream", 1)[1].split("def gateway_claim", 1)[0]
    assert 'jsonable_encoder(items)' in route
    assert 'event_payload = json.dumps' in route
    assert 'yield "data: " + event_payload' in route
    assert "attach_agent_database_context=False" in route


def test_barrier_arrival_keeps_shared_state_update_in_control_plane_context():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    route = source.split("def gateway_arrival", 1)[1].split("def gateway_action", 1)[0]
    assert 'request, "barriers.arrive", operation="barriers.arrive"' in route
    assert "attach_agent_database_context=False" in route
    assert "agent_gateway_api.submit_arrival" in route


def test_external_agent_instance_creation_is_a_control_plane_transaction():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    route = source.split("def gateway_instance", 1)[1].split("def gateway_events", 1)[0]
    assert 'operation="instances.create"' in route
    assert "attach_agent_database_context=False" in route
    assert "agent_gateway_api.create_instance" in route


def test_gateway_heartbeat_projects_lease_and_posture_in_control_plane():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    route = source.split("def gateway_heartbeat", 1)[1].split("def gateway_containment", 1)[0]
    assert 'operation="heartbeat"' in route
    assert "attach_agent_database_context=False" in route


def test_shared_gateway_mutations_do_not_expand_dedicated_login_table_writes():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    for function, successor in (
        ("gateway_embedding_probe", "gateway_embeddings"),
        ("gateway_message", "gateway_memory_candidate"),
        ("gateway_action", "runtime_profile"),
    ):
        route = source.split(f"def {function}", 1)[1].split(f"def {successor}", 1)[0]
        assert "attach_agent_database_context=False" in route


def test_agent_management_gateway_uses_fenced_control_plane_tables():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    for function, successor in (
        ("gateway_containment", "gateway_containment_ack"),
        ("gateway_containment_ack", "gateway_upgrade_vote"),
        ("gateway_upgrade_vote", "gateway_upgrade_node"),
        ("gateway_upgrade_node", "gateway_pending_upgrade_skills"),
        ("gateway_pending_upgrade_skills", "gateway_upgrade_skill_ack"),
        ("gateway_upgrade_skill_ack", "gateway_management_artifact_receipt"),
        ("gateway_management_artifact_receipt", "gateway_evidence"),
    ):
        route = source.split(f"def {function}", 1)[1].split(f"def {successor}", 1)[0]
        assert "attach_agent_database_context=False" in route


def test_human_and_gateway_request_entries_clear_reused_worker_agent_context():
    source = WEB_APP_SOURCE.read_text(encoding="utf-8")
    principal_route = source.split("def principal(", 1)[1].split("def require_csrf", 1)[0]
    gateway_context = source.split("def _gateway_context(", 1)[1].split("def _gateway_activation_credential", 1)[0]
    assert 'getattr(connection, "set_agent_context", None)' in principal_route
    assert "clear_context(None)" in principal_route
    assert 'getattr(connection, "set_agent_context", None)' in gateway_context
    assert "clear_context(None)" in gateway_context
    assert "finally:" in source.split("def _gateway_request_context", 1)[1].split("def _reclaim_local_agents", 1)[0]
    gateway_definitions = source.count("\ndef gateway_")
    decorated_gateways = source.count("\n@_gateway_request_context\ndef gateway_")
    assert decorated_gateways == gateway_definitions


def test_remediation_without_operator_deadline_uses_one_consistent_default():
    source = (LIB_SOURCE / "compliance_api.py").read_text(encoding="utf-8")
    function = source.split("def create_remediation", 1)[1].split("def respond_remediation", 1)[0]
    assert "effective_deadline = deadline_at or" in function
    assert "database_deadline = datetime.fromisoformat" in function
    assert '"deadline_at": database_deadline' in function
    assert "deadline_at=effective_deadline" in function


def test_notification_deadline_binds_as_cross_adapter_datetime():
    source = (LIB_SOURCE / "identity_api.py").read_text(encoding="utf-8")
    function = source.split("def enqueue_notification", 1)[1].split("def list_notifications", 1)[0]
    assert "database_deadline = _timestamp(deadline_at)" in function
    assert '"deadline_at": database_deadline' in function
    assert ":notification_level" in function
    assert '"notification_level": normalized["level"]' in function
    assert ":level" not in function


def test_containment_signs_iso_but_binds_local_database_expiry():
    source = (LIB_SOURCE / "admin_management.py").read_text(encoding="utf-8")
    function = source.split("def issue_containment", 1)[1].split("def pull_containment_command", 1)[0]
    assert "datetime.now().astimezone().replace(tzinfo=None)" in function
    assert "expiry = expiry_at.isoformat()" in function
    assert '"expires": expiry_at' in function


def test_community_external_agent_activation_avoids_enterprise_posture_tables():
    identity = (LIB_SOURCE / "identity_api.py").read_text(encoding="utf-8")
    redeem = identity.split("def redeem_enrollment", 1)[1].split("def activate_community_agent", 1)[0]
    community = identity.split("def activate_community_agent", 1)[1].split("def list_enrollment_grants", 1)[0]
    assert "if _compliance_enabled():" in redeem
    assert "CX_AGENT_POSTURES" in redeem
    assert "CX_AGENT_POSTURES" not in community
    assert "COMMUNITY_GATEWAY_ACTIVATE" in community
    web = WEB_APP_SOURCE.read_text(encoding="utf-8")
    enterprise_paths = web.split("_ENTERPRISE_COMPLIANCE_PATHS =", 1)[1].split(")", 1)[0]
    assert '"/api/gateway/activate"' not in enterprise_paths
    assert "identity_api.activate_community_agent" in web


@pytest.mark.skipif(GENERATED and GENERATED_DATABASE != "pg", reason="PostgreSQL package contract")
def test_pg_external_agent_domain_context_is_database_scoped():
    deploy = DEPLOY_SOURCE if GENERATED else ROOT / "adapters" / "pg" / "deploy"
    sql = (deploy / "65_v4_4_10_external_agent_domain_context.sql").read_text(encoding="utf-8").upper()
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "CX_DOMAIN_MEMBERS_AGENT_SELF" in sql
    assert "PRINCIPAL_ID = PUBLIC.CURRENT_AGENT_IDENTITY()" in sql
    assert "CX_SECURITY_DOMAINS_AGENT_MEMBER" in sql


@pytest.mark.skipif(GENERATED and GENERATED_DATABASE != "pg", reason="PostgreSQL package contract")
def test_pg_agent_database_role_is_namespaced_by_database():
    source = (
        (LIB_SOURCE / "agent_api.py") if GENERATED
        else (ROOT / "adapters" / "pg" / "agent_api.py")
    ).read_text(encoding="utf-8")
    function = source.split("def _agent_role_name", 1)[1].split("def _provision_agent_login", 1)[0]
    assert "database_name" in function
    assert 'f"{namespace}\\0{agent_id}"' in function
    provision = source.split("def _provision_agent_login", 1)[1].split("def ensure_external_agent_identity", 1)[0]
    assert "_agent_role_name(agent_id, db_cfg.dbname)" in provision


@pytest.mark.skipif(GENERATED, reason="cross-adapter authorization migration is a unified-source gate")
def test_external_embedding_authorization_is_declared_for_all_adapters():
    markers = {
        "CX_EMBEDDING_ACCESS_GRANTS", "AGENT", "TEMPLATE", "ORGANIZATION",
        "SECURITY_DOMAIN", "ALLOW", "DENY",
    }
    for database in ("oracle", "pg", "yashandb"):
        source = (ROOT / "adapters" / database / "deploy" / "61_v4_4_10_external_embedding_authorization.sql").read_text(encoding="utf-8").upper()
        assert markers <= {marker for marker in markers if marker in source}


@pytest.mark.skipif(GENERATED, reason="cross-adapter registration migration is a unified-source gate")
def test_agent_embedding_registration_contract_is_declared_for_all_adapters():
    required = {"EMBEDDING_MODE", "EMBEDDING_MODEL_ID", "EMBEDDING_FINGERPRINT", "EMBEDDING_DIMENSION", "EMBEDDING_DISTANCE_METRIC", "EMBEDDING_NORMALIZE"}
    for database in ("oracle", "pg", "yashandb"):
        source = (ROOT / "adapters" / database / "deploy" / "62_v4_4_10_agent_embedding_contract.sql").read_text(encoding="utf-8").upper()
        assert required <= {marker for marker in required if marker in source}


def test_agent_managed_embedding_allows_different_name_with_matching_fingerprint(monkeypatch):
    monkeypatch.setattr(embedding_governance, "effective_binding", lambda: {
        "ready": True,
        "profile": {"model_id": "provider-bge-m3", "dimension": 1024, "distance_metric": "COSINE", "normalize_vectors": "Y"},
        "contract": {"model_fingerprint": "sha256:approved", "dimension": 1024, "distance_metric": "COSINE", "normalize_vectors": "Y"},
    })
    assert agent_registration.validate_embedding_declaration(
        "AGENT_MANAGED", model_id="local-bge-m3", fingerprint="sha256:approved",
        dimension=1024, distance_metric="COSINE", normalize=True,
    ) == "AGENT_MANAGED"
    with pytest.raises(ValueError, match="fingerprint"):
        agent_registration.validate_embedding_declaration(
            "AGENT_MANAGED", model_id="local-bge-m3", fingerprint="sha256:different",
            dimension=1024, distance_metric="COSINE", normalize=True,
        )


@pytest.mark.skipif(GENERATED, reason="source route inspection is a unified-source gate")
def test_embedding_token_issuance_and_calls_recheck_database_authorization():
    app = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    governance = (ROOT / "shared" / "lib" / "embedding_governance.py").read_text(encoding="utf-8")
    token_route = app.split('def gateway_token(body: GatewayTokenBody)', 1)[1].split('@app.post("/api/gateway/instances")', 1)[0]
    gateway = governance.split("def gateway_embeddings(", 1)[1].split("def validate_vector_write", 1)[0]
    mutations = governance.split("def upsert_access_grant(", 1)[1].split("def _run_managed_job", 1)[0]
    assert 'if "embedding.generate" in requested:' in token_route
    assert "require_embedding_gateway_access(body.agent_id)" in token_route
    assert "require_embedding_gateway_access(actor)" in gateway
    assert "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP" in governance
    assert mutations.count("_revoke_subject_tokens(") >= 2


@pytest.mark.skipif(GENERATED, reason="source/package static path inspection is a unified-source gate")
def test_generated_package_brand_asset_is_resolved_from_scripts_directory():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    assert 'Path(__file__).resolve().parent / "scripts" / "visualization" / "static" / file_path' in source


@pytest.mark.skipif(GENERATED, reason="source UI inspection is a unified-source gate")
def test_external_registration_panel_exposes_external_database_endpoint_form():
    source = (ROOT / "shared" / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    panel = source.split("function ExternalRegistrationPolicyPanel(", 1)[1].split("function AdminAgentStoragePanel(", 1)[0]
    assert "External Agent database endpoint" in panel
    assert "/api/platform/external-db-endpoints" in panel
    assert 'name="host_reference"' in panel
    assert 'name="tls_required"' in panel
    assert "database passwords or keys" in panel


@pytest.mark.skipif(GENERATED, reason="source/package static path inspection is a unified-source gate")
def test_external_agent_token_distributes_scoped_database_endpoint():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    token_route = source.split("def gateway_token", 1)[1].split("def gateway_database_endpoint", 1)[0]
    assert 'issued["database_endpoint"] = platform_agent_pool.discover_agent_endpoint(body.agent_id)' in token_route
    assert '"database.endpoint"' in token_route
    assert 'def gateway_database_endpoint' in source
    endpoint_route = source.split("def gateway_database_endpoint", 1)[1].split("def gateway_instance", 1)[0]
    assert "attach_agent_database_context=False" in endpoint_route
    assert '"Database passwords, keys, and other connection secrets' not in source


@pytest.mark.skipif(GENERATED, reason="source/package static path inspection is a unified-source gate")
def test_external_endpoint_defaults_to_platform_public_target_and_keeps_service_name():
    source = (ROOT / "shared" / "lib" / "platform_agent_pool.py").read_text(encoding="utf-8")
    discovery = source.split("def discover_agent_endpoint", 1)[1].split("def register_endpoint", 1)[0]
    assert "EXTERNAL_GLOBAL" in discovery
    assert "ORDER BY CREATED_AT DESC" in discovery
    assert '"service_name"' in discovery
    assert "_configured_database_endpoint()" in discovery


def test_oracle_and_yashandb_dsn_metadata_is_preserved_for_external_agents(monkeypatch):
    try:
        from shared.lib import platform_agent_pool
    except ModuleNotFoundError:
        from lib import platform_agent_pool

    class Database:
        dsn = "<DB_HOST>:1688/ai_agent"

    class Config:
        database = Database()

    import importlib
    config_module = importlib.import_module(platform_agent_pool.__package__ + ".config")
    monkeypatch.setattr(config_module, "get_config", lambda: Config())
    endpoint = platform_agent_pool._configured_database_endpoint()
    assert endpoint["host"].casefold() == Database.dsn.split(":", 1)[0].casefold()
    assert endpoint["port"] == 1688
    assert endpoint["service_name"] == "ai_agent"
    assert endpoint["dbname"] == "ai_agent"


def test_embedding_grant_insert_uses_exact_oracle_bind_set(monkeypatch):
    class Tx:
        def __init__(self):
            self.executed = []

        def query_one(self, sql, _params):
            if "CX_PRINCIPALS" in sql:
                return {"principal_id": "AGENT_1"}
            if "CX_EMBEDDING_ACCESS_GRANTS" in sql:
                return None
            return None

        def execute(self, sql, params):
            self.executed.append((sql, dict(params)))
            return 1

    tx = Tx()
    try:
        from shared.lib import embedding_governance
    except ModuleNotFoundError:
        from lib import embedding_governance
    monkeypatch.setattr(embedding_governance.connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(embedding_governance.identity_api, "_audit_tx", lambda *_args: None)
    result = embedding_governance.upsert_access_grant(
        "ADMIN", subject_type="AGENT", subject_id="AGENT_1", effect="ALLOW",
        max_batch_size=2, max_input_chars=8000, reason="approved external embedding",
    )
    import re
    sql, params = next(item for item in tx.executed if "INSERT INTO CX_EMBEDDING_ACCESS_GRANTS" in item[0])
    assert set(re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql)) == set(params)
    assert result["effect"] == "ALLOW"
    assert any("CX_AGENT_ACCESS_TOKENS" in sql for sql, _params in tx.executed)


@pytest.mark.skipif(GENERATED, reason="source release-gate inspection is a unified-source gate")
def test_client_backup_tool_is_not_part_of_the_release_contract():
    import re

    build = (ROOT / "build.py").read_text(encoding="utf-8")
    validator = (ROOT / "spec_validator.py").read_text(encoding="utf-8")

    assert not (ROOT / "tools" / "v410_pre57_backup.py").exists()
    assert '"v410_pre57_backup.py"' not in build
    allowlist = validator.split("dialect_boundary_dual_files = {", 1)[1].split("}", 1)[0]
    assert set(re.findall(r'\"([^\"]+\.py)\"', allowlist)) == {"migration_runner.py"}


@pytest.mark.skipif(GENERATED, reason="cross-adapter validator closure is a unified-source gate")
def test_live_validator_selects_and_checks_the_v410_contract():
    for database in ("oracle", "pg", "yashandb"):
        deploy = ROOT / "adapters" / database / "deploy"
        scripts = [deploy / name for name in live_db_validator.V410_MIGRATION_SCRIPTS]
        if database == "pg":
            scripts.extend([deploy / "51_v4_4_9_identity_boundary_repair.sql", deploy / "53_v4_4_9_pg_runtime_boundary.sql"])
        result = live_db_validator.validate_v410_static_contract(database, scripts)
        assert result["passed"] is True, result


@pytest.mark.skipif(GENERATED, reason="cross-edition validator closure is a unified-source gate")
def test_v410_community_static_contract_omits_enterprise_compliance_overlay():
    deploy = ROOT / "adapters" / "oracle" / "deploy"
    scripts = [
        deploy / name
        for name in live_db_validator.migration_scripts_for_edition(
            live_db_validator.V410_MIGRATION_SCRIPTS, "community"
        )
    ]
    result = live_db_validator.validate_v410_static_contract(
        "oracle", scripts, "community"
    )
    control = result["v410_model_usage_wallboard"]
    assert result["passed"] is True, result
    assert "29_v4_3_4_agent_compliance.sql" not in control["scripts_required"]
    assert "30_v4_3_4_compliance_hardening.sql" not in control["scripts_required"]


@pytest.mark.skipif(GENERATED, reason="cross-edition validator closure is a unified-source gate")
def test_v410_enterprise_static_contract_still_requires_compliance_overlay():
    deploy = ROOT / "adapters" / "oracle" / "deploy"
    scripts = [
        deploy / name
        for name in live_db_validator.V410_MIGRATION_SCRIPTS
        if name not in live_db_validator.ENTERPRISE_ONLY_MIGRATION_SCRIPTS
    ]
    result = live_db_validator.validate_v410_static_contract(
        "oracle", scripts, "enterprise"
    )
    missing = result["v410_model_usage_wallboard"]["scripts_missing"]
    assert result["passed"] is False
    assert set(missing) == live_db_validator.ENTERPRISE_ONLY_MIGRATION_SCRIPTS


@pytest.mark.skipif(GENERATED and GENERATED_DATABASE != "oracle", reason="Oracle package contract")
def test_oracle_external_gateway_migration_supports_community_data_roles():
    deploy = DEPLOY_SOURCE if GENERATED else ROOT / "adapters" / "oracle" / "deploy"
    source = (deploy / "63_v4_4_10_external_agent_gateway_grants.sql").read_text(encoding="utf-8").upper()
    assert "CREATE DATA ROLE AGENT_DATA_ROLE" in source
    assert "CREATE DATA ROLE POOL_AGENT_DATA_ROLE" in source
    assert source.count("SQLCODE != -52514") == 2
    assert "GRANT DEEP_SEC_SESSION_ROLE TO AGENT_DATA_ROLE" in source
    assert "USER_TABLES WHERE TABLE_NAME='CX_AGENT_POSTURES'" in source
    assert "USER_TABLES WHERE TABLE_NAME='CX_AGENT_POSTURE_EVIDENCE'" in source


@pytest.mark.skipif(GENERATED and GENERATED_DATABASE != "pg", reason="PostgreSQL package contract")
def test_pg_external_context_repair_treats_compliance_as_enterprise_overlay():
    deploy = DEPLOY_SOURCE if GENERATED else ROOT / "adapters" / "pg" / "deploy"
    source = (deploy / "64_v4_4_10_external_agent_context_repair.sql").read_text(encoding="utf-8").lower()
    assert "to_regclass('public.cx_agent_postures') is not null" in source
    assert "to_regclass('public.cx_agent_posture_evidence') is not null" in source
    assert "force row level security" in source


@pytest.mark.skipif(GENERATED and GENERATED_DATABASE != "yashandb", reason="YashanDB package contract")
def test_yashandb_security_repair_uses_the_configured_schema_owner():
    deploy = DEPLOY_SOURCE if GENERATED else ROOT / "adapters" / "yashandb" / "deploy"
    source = (deploy / "50_v4_4_9_security_boundary_repair.sql").read_text(encoding="utf-8").upper()
    assert "AIADMIN." not in source
    assert "ON CX_PLATFORM_KNOWLEDGE FROM DEEP_SEC_SESSION_ROLE" in source


def test_v410_live_contract_requires_external_embedding_authorization_table():
    assert "CX_EMBEDDING_ACCESS_GRANTS" in live_db_validator.V410_MODEL_TABLES
    source = RUNNER_SOURCE.read_text(encoding="utf-8")
    completeness = source.split('if key == "61_v4_4_10_external_embedding_authorization":', 1)[1].split("if key ==", 1)[0]
    assert "CX_EMBEDDING_ACCESS_GRANTS" in completeness
    assert "MAX_BATCH_SIZE" in completeness
    assert "MAX_INPUT_CHARS" in completeness
    step_57 = source.split('if key == "57_v4_4_10_complete_model_governance":', 1)[1].split("if key ==", 1)[0]
    assert '- {"CX_EMBEDDING_ACCESS_GRANTS"}' in step_57


@pytest.mark.skipif(GENERATED, reason="source module inspection is a unified-source gate")
def test_model_usage_contract_does_not_log_payloads_or_float_costs():
    source = (ROOT / "shared" / "lib" / "model_usage_api.py").read_text(encoding="utf-8")
    assert "prompt/response bodies" in source
    assert "Decimal(" in source
    assert "PROVIDER_REPORTED" in source
    assert "INCOMPLETE" in source
    assert "Authorization" in source
    assert "decrypt_section" in source


@pytest.mark.skipif(GENERATED, reason="route source inspection is a unified-source gate")
def test_wallboard_route_is_read_only_and_scoped():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/wallboard")' in source
    wallboard_route = source.split('@app.get("/api/wallboard")', 1)[1].split("\n\n", 1)[0]
    assert 'Depends(require_action("wallboard.read"))' in wallboard_route
    assert 'Depends(require_action("agents.read"))' not in wallboard_route
    assert "@app.post(\"/api/wallboard\")" not in source


@pytest.mark.skipif(GENERATED, reason="route source inspection is a unified-source gate")
def test_model_usage_routes_use_separate_reporting_and_forwarding_permissions():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    reporting = source.split('@app.get("/api/model-usage/summary")', 1)[1].split("\n\n", 1)[0]
    forwarding = source.split('def model_forward_authorization', 1)[1].split('@app.get("/api/model-usage/summary")', 1)[0]
    assert 'Depends(require_action("model_usage.read"))' in reporting
    assert 'model_gateway.forward' in forwarding
    assert 'authenticate_gateway_credential' in (ROOT / "shared" / "lib" / "model_usage_api.py").read_text(encoding="utf-8")
    assert 'Depends(require_action("agents.read"))' not in reporting + forwarding


@pytest.mark.skipif(GENERATED, reason="route source inspection is a unified-source gate")
def test_oci_readiness_is_distinct_from_process_liveness():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/health")' in source
    assert '@app.get("/api/ready")' in source
    readiness = source.split('@app.get("/ready")', 1)[1].split('@app.get("/app")', 1)[0]
    assert "CX_PLATFORM_CAPABILITIES" in readiness
    assert "response.status_code = 503" in readiness
    assert '"status": "not_ready"' in readiness


@pytest.mark.skipif(GENERATED, reason="cross-adapter seed equivalence is a unified-source gate")
def test_v410_seeds_wallboard_capability_registry():
    for database in ("oracle", "pg", "yashandb"):
        source = "\n".join(
            (ROOT / "adapters" / database / "deploy" / name).read_text(encoding="utf-8").lower()
            for name in ("55_v4_4_10_model_usage_wallboard.sql", "56_v4_4_10_runtime_repair.sql")
        )
        assert "wallboard" in source
        assert "cx_platform_capabilities" in source


def test_v410_runtime_registry_matches_new_database_capabilities():
    try:
        from shared.lib import platform_capabilities
    except ModuleNotFoundError:
        from lib import platform_capabilities

    assert {"model_finance", "external_model_evidence"} <= set(platform_capabilities.REGISTRY)
    assert platform_capabilities.DEPENDENCIES["model_finance"] == ("audit_write",)
    assert platform_capabilities.DEPENDENCIES["external_model_evidence"] == ("audit_write",)


@pytest.mark.skipif(GENERATED, reason="PostgreSQL source inspection runs in the unified-source gate")
def test_v410_postgresql_rls_uses_the_runtime_identity_boundary():
    source = (ROOT / "adapters" / "pg" / "deploy" / "56_v4_4_10_runtime_repair.sql").read_text(encoding="utf-8")
    assert "app.current_principal_id" not in source
    assert "public.current_agent_identity()" in source
    assert "cx_model_credentials_owner" in source


def test_gateway_credential_enforces_forward_and_target_scopes(monkeypatch):
    monkeypatch.setattr(
        model_usage_api,
        "_credential",
        lambda _raw: {
            "credential_id": "GWC_1", "created_by": "HP_OWNER",
            "scopes_json": '["model.forward","profile:PROFILE_1","agent:AGENT_1"]',
        },
    )
    context = model_usage_api.authenticate_gateway_credential("cxgw_secret", "PROFILE_1", "AGENT_1")
    assert context["actor_principal_id"] == "HP_OWNER"
    try:
        model_usage_api.authenticate_gateway_credential("cxgw_secret", "PROFILE_2", "AGENT_1")
    except PermissionError:
        pass
    else:
        raise AssertionError("profile-restricted credential accepted another profile")


def test_idempotency_conflicts_are_stable_and_payload_bound(monkeypatch):
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query_one",
        lambda *_args, **_kwargs: {"request_id": "LMR_1", "input_digest": "digest-a", "status": "SUCCEEDED"},
    )
    for digest in ("digest-a", "digest-b"):
        try:
            model_usage_api._reserve_idempotency("HP_1", "same-key", digest)
        except model_usage_api.ModelUsageConflict:
            pass
        else:
            raise AssertionError("duplicate idempotency key was accepted")


def test_routing_boolean_encoding_is_adapter_explicit(monkeypatch):
    monkeypatch.setattr(model_usage_api.connection, "DATABASE_DIALECT", "oracle")
    assert model_usage_api._db_bool(True) == "Y"
    assert model_usage_api._db_bool(False) == "N"
    assert model_usage_api._as_bool("Y") is True
    assert model_usage_api._as_bool("N") is False
    monkeypatch.setattr(model_usage_api.connection, "DATABASE_DIALECT", "postgresql")
    assert model_usage_api._db_bool(True) is True


def test_routing_change_updates_the_existing_policy(monkeypatch):
    monkeypatch.setattr(model_usage_api.identity_api, "effective_access", lambda *_args: {"decision": "ALLOW"})
    monkeypatch.setattr(model_usage_api.connection, "execute_query_one", lambda *_args, **_kwargs: {"policy_id": "MRP_1"})
    writes = []
    monkeypatch.setattr(model_usage_api.connection, "execute", lambda sql, params: writes.append((sql, params)) or 1)
    result = model_usage_api.set_routing_policy("HP_ADMIN", "", "PROFILE_1", True, False, "approved", "https://example.test/api/model-gateway/completions")
    assert writes and writes[0][0].startswith("UPDATE CX_MODEL_ROUTING_POLICIES")
    assert result["policy_id"] == "MRP_1"


def test_wallboard_agent_totals_use_one_registered_agent_population(monkeypatch):
    monkeypatch.setattr(
        model_usage_api.identity_api,
        "effective_access",
        lambda *_args, **_kwargs: {"decision": "ALLOW"},
    )
    monkeypatch.setattr(
        model_usage_api,
        "usage_summary",
        lambda *_args, **_kwargs: {
            "items": [],
            "generated_at": "2026-08-21T00:00:00Z",
            "coverage": {"observed": True, "unobserved": "unknown"},
        },
    )
    monkeypatch.setattr(model_usage_api.connection, "execute_query", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query_one",
        lambda *_args, **_kwargs: {"total": 2, "active": 2},
    )
    monkeypatch.setattr(
        monitor_api,
        "get_system_overview",
        lambda _actor=None, _resource_scope=None: {
            "agents": {"total": 14, "online": 14, "busy": 3},
            "sessions": {"active": 4},
            "tasks": {"running_plans": 2, "running_loops": 1},
            "stalled_count": 0,
        },
    )

    result = model_usage_api.wallboard("admin")

    assert result["agents"] == {
        "total": 14,
        "online": 14,
        "busy": 3,
        "native_total": 2,
        "native_active": 2,
    }


def test_wallboard_uses_one_authorized_agent_scope(monkeypatch):
    accesses = []
    monkeypatch.setattr(
        model_usage_api.identity_api,
        "effective_access",
        lambda _actor, action: accesses.append(action) or {"decision": "ALLOW"},
    )
    monkeypatch.setattr(
        model_usage_api.identity_api,
        "_agent_visibility_clause",
        lambda _actor: "p.PRINCIPAL_ID='AGENT_VISIBLE'",
    )
    queries = []
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query",
        lambda sql, params=None: queries.append((sql, params)) or [],
    )
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query_one",
        lambda *_args, **_kwargs: {"total": 0, "active": 0},
    )
    monkeypatch.setattr(
        monitor_api,
        "get_system_overview",
        lambda actor=None, resource_scope=None: {
            "agents": {"total": 1, "online": 1, "busy": 0},
            "sessions": {"active": 0}, "tasks": {"running_plans": 0, "running_loops": 0},
            "stalled_count": 0, "scope_actor": actor,
        },
    )
    monkeypatch.setattr(monitor_api, "_overview_agent_scope", lambda actor, alias="a", resource_scope=None: ("1=0", {"principal_id": actor}))

    result = model_usage_api.wallboard("MANAGER")

    assert result["runtime"]["scope_actor"] == "MANAGER"
    assert all("AGENT_VISIBLE" in sql for sql, _params in queries)
    assert all(params == {"actor": "MANAGER"} for _sql, params in queries)
    assert "agents.read" not in accesses


def test_wallboard_marks_runtime_failure_as_partial_not_zero(monkeypatch):
    monkeypatch.setattr(model_usage_api.identity_api, "effective_access", lambda *_args: {"decision": "ALLOW"})
    monkeypatch.setattr(model_usage_api, "usage_summary", lambda *_args, **_kwargs: {
        "items": [], "generated_at": "2026-08-23T00:00:00Z", "coverage": {},
    })
    monkeypatch.setattr(model_usage_api.connection, "execute_query", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(model_usage_api.connection, "execute_query_one", lambda *_args, **_kwargs: {"total": 0, "active": 0})
    monkeypatch.setattr(monitor_api, "get_system_overview", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database detail must not leak")))
    monkeypatch.setattr(monitor_api, "_overview_agent_scope", lambda *_args, **_kwargs: ("1=0", {}))

    result = model_usage_api.wallboard("ADMIN")

    assert result["partial"] is True
    assert result["freshness"] == "DEGRADED"
    assert result["sources"]["runtime"] == {
        "status": "UNAVAILABLE", "error_code": "RUNTIME_OVERVIEW_UNAVAILABLE",
    }
    assert result["agents"]["total"] is None
    assert result["runtime"]["sessions"]["active"] is None
    assert "database detail" not in str(result)


def test_wallboard_organization_scope_follows_primary_owner_membership(monkeypatch):
    monkeypatch.setattr(identity_api, "_agent_visibility_clause", lambda _actor: "1=1")

    sql, params = monitor_api._overview_agent_scope(
        "ADMIN", resource_scope={"organization_id": "ORG_ROOT"},
    )

    assert "CX_AGENT_RELATIONSHIPS" in sql and "PRIMARY_OWNER" in sql
    assert "CX_ORGANIZATION_MEMBERS" in sql and "CX_ORGANIZATION_CLOSURE" in sql
    assert "wom.PRINCIPAL_ID=war.PRINCIPAL_ID" in sql
    assert params["wallboard_org"] == "ORG_ROOT"
