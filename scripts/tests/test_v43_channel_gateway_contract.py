"""Pure source contracts for the v4.3 Channel and Agent Gateway boundary."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _databases() -> tuple[str, ...]:
    """Use all adapters in the source tree and the one adapter in a package."""
    manifest = ROOT / "build-manifest.json"
    if manifest.is_file():
        try:
            key = str(json.loads(manifest.read_text(encoding="ascii")).get("database", {}).get("key", ""))
        except (OSError, ValueError, TypeError):
            key = ""
        if key in {"oracle", "pg", "yashandb"}:
            return (key,)
    return ("oracle", "pg", "yashandb")


def _source(path: str) -> str:
    source_path = ROOT / path
    if source_path.is_file():
        return source_path.read_text(encoding="utf-8")

    # Generated archives flatten the adapter/shared source into scripts/. Keep
    # source contracts runnable from both layouts without shipping the source
    # tree itself in a release archive.
    if path.startswith("shared/"):
        relative = path.removeprefix("shared/")
        for generated_path in (ROOT / relative, ROOT / "scripts" / relative):
            if generated_path.is_file():
                return generated_path.read_text(encoding="utf-8")
    if path.startswith("adapters/") and "/deploy/" in path:
        generated_path = ROOT / "scripts" / "deploy" / path.split("/deploy/", 1)[1]
        if generated_path.is_file():
            return generated_path.read_text(encoding="utf-8")
    raise FileNotFoundError(path)


def _frontend_asset(extension: str) -> str:
    """Load the current Vite asset in source and generated package layouts."""
    asset_roots = (
        ROOT / "shared" / "web" / "dist" / "assets",
        ROOT / "web" / "dist" / "assets",
    )
    matches = sorted(
        path for asset_root in asset_roots
        if asset_root.is_dir()
        for path in asset_root.glob(f"index-*{extension}")
        if path.is_file()
    )
    if matches:
        return matches[0].read_text(encoding="utf-8")
    legacy_name = {".js": "app.js", ".css": "app.css"}.get(extension)
    if legacy_name:
        return _source(f"shared/web/dist/{legacy_name}")
    raise FileNotFoundError(f"frontend asset *{extension}")


def _sql_function_definition(source: str, function_name: str) -> str:
    """Return one dollar-quoted PostgreSQL function definition."""
    marker = f"create or replace function public.{function_name}("
    start = source.find(marker)
    assert start >= 0, f"missing PostgreSQL function: {function_name}"
    match = re.search(
        r"\bas\s+\$(?P<tag>[a-z0-9_]*)\$(?P<body>.*?)\$(?P=tag)\$;",
        source[start:],
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert match, f"unterminated PostgreSQL function: {function_name}"
    return source[start:start + match.end()]


def test_web_exposes_claim_ack_member_and_fenced_arrival_routes():
    source = _source("shared/web_app.py")
    tree = ast.parse(source)
    routes = {
        decorator.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in {"get", "post", "delete"}
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
    }
    assert "/api/gateway/events/claim" in routes
    assert "/api/agent-gateway/events/claim" in routes
    assert "/api/gateway/events/{delivery_id}/ack" in routes
    assert "/api/channels/{channel_id}/members" in routes
    assert "/api/channels/{channel_id}/members/{member_principal_id}" in routes
    assert "claim_token=body.claim_token" in source
    assert "agent_gateway_api.submit_arrival" in source
    assert "p.PRINCIPAL_TYPE = 'AGENT'" in source


def test_gateway_persists_claim_digest_and_fencing_before_ack():
    source = _source("shared/lib/agent_gateway_api.py")
    assert "CLAIM_TOKEN_DIGEST" in source
    assert "FENCING_TOKEN = :fencing_token" in source
    assert "DEAD_LETTER" in source
    assert "AND CLAIM_TOKEN_DIGEST = :claim_token_digest" in source
    assert "i.LEASE_EXPIRES_AT > CURRENT_TIMESTAMP" in source
    assert "p.STATUS = 'ACTIVE'" in source
    assert "SET STATUS = 'PENDING', CLAIMED_BY = NULL" in source
    assert "AND t.AGENT_ID = i.AGENT_ID" in source


def test_identity_boundary_fails_closed_and_serializes_enrollment_redeem():
    source = _source("shared/lib/identity_api.py")
    assert "principal:inactive-or-unknown" in source
    assert "principal_status != \"ACTIVE\"" in source
    assert "SELECT TOKEN_ID FROM CX_ENROLLMENT_TOKENS WHERE TOKEN_ID = :token_id FOR UPDATE" in source
    assert "SELECT GRANT_ID FROM CX_ENROLLMENT_GRANTS WHERE GRANT_ID = :grant_id FOR UPDATE" in source
    assert "m.REDACTED_AT IS NULL" in source
    assert "p.STATUS = 'ACTIVE' ORDER BY m.JOINED_AT" in source


def test_channel_and_instance_scope_cannot_lower_security_classification():
    identity = _source("shared/lib/identity_api.py")
    gateway = _source("shared/lib/agent_gateway_api.py")
    assert "_classification_meets_minimum(classification, domain.get(\"classification\")" in identity
    assert "Channel classification is below the Security Domain minimum" in identity
    assert "security domain is required for an unbound instance" in gateway
    assert "agent is not a member of the security domain" in gateway
    assert "instance classification is below the Security Domain minimum" in gateway


def test_channel_member_addition_requires_domain_membership_and_reason():
    source = _source("shared/lib/agent_gateway_api.py")
    assert "membership addition reason is required" in source
    assert "CX_DOMAIN_MEMBERS" in source
    assert "member is outside the Channel security domain" in source
    assert "CHANNEL_MEMBER_ADD" in source
    assert "MEMBER_ROLE <> 'OWNER'" in source


def test_all_database_migrations_have_split_additive_claim_guards():
    for database in _databases():
        source = _source(f"adapters/{database}/deploy/16_v4_3_0_identity_channels.sql").upper()
        for column in ("LEASE_EXPIRES_AT", "CLAIM_TOKEN_DIGEST", "CLAIMED_AT", "FENCING_TOKEN"):
            assert column in source
    for database in _databases():
        if database not in {"oracle", "yashandb"}:
            continue
        source = _source(f"adapters/{database}/deploy/16_v4_3_0_identity_channels.sql").upper()
        assert source.count("ALTER TABLE CX_AGENT_DELIVERIES ADD") == 3
        assert "ALTER TABLE CX_AGENT_ACCESS_TOKENS ADD" in source
        assert "ALTER TABLE CX_BARRIERS ADD" in source
    if "pg" in _databases():
        pg = _source("adapters/pg/deploy/16_v4_3_0_identity_channels.sql").lower()
        assert "add column if not exists fencing_token" in pg
        assert "add column if not exists created_by" in pg


def test_pg_governance_tables_have_agent_rls_and_no_cross_channel_policy():
    if "pg" not in _databases():
        return
    source = _source("adapters/pg/deploy/16_v4_3_0_identity_channels.sql").lower()
    assert "cx_agent_channel_member" in source
    for table in (
        "cx_principals", "cx_agent_relationships", "cx_agent_credentials",
        "cx_agent_access_tokens", "cx_agent_instances", "cx_agent_deliveries",
        "cx_channels", "cx_channel_members", "cx_channel_messages", "cx_barriers",
        "cx_barrier_arrivals", "cx_action_cards", "cx_security_events",
    ):
        assert f"alter table {table} enable row level security" in source
    assert "principal_id = public.current_agent_identity()" in source
    assert "public.cx_agent_channel_member(channel_id, public.current_agent_identity())" in source
    assert "b.channel_id is not null" in source
    assert "b.created_by = public.current_agent_identity()" in source


def test_pg_thread_participants_are_snapshot_bounded_and_functions_are_single_definition():
    if "pg" not in _databases():
        return
    source = _source("adapters/pg/deploy/17_v4_3_0_governance_lifecycle.sql").lower()

    for function_name in (
        "cx_channel_principal_member",
        "cx_channel_principal_type",
        "cx_channel_thread_member",
        "cx_channel_thread_participant",
        "cx_channel_thread_participant_snapshot_guard",
        "cx_enqueue_channel_deliveries",
    ):
        marker = f"create or replace function public.{function_name}("
        assert source.count(marker) == 1
        definition = _sql_function_definition(source, function_name)
        assert "security definer" in definition
        assert "set search_path = pg_catalog, public" in definition

    participant = _sql_function_definition(source, "cx_channel_thread_participant")
    assert "t.created_by = public.current_agent_identity()" in participant
    assert "t.thread_type in ('private', 'direct')" in participant
    assert "public.cx_channel_principal_member(t.channel_id, p_principal_id)" in participant
    assert "jsonb_typeof(" in participant
    assert "'participant_principal_ids'" in participant
    assert ") ? public.current_agent_identity()" in participant
    assert ") ? p_principal_id" in participant
    assert "p_principal_id = public.current_agent_identity()" not in participant

    policy_start = source.index("create policy cx_channel_threads_member")
    assert source.index("create or replace function public.cx_channel_thread_participant(") < policy_start
    assert "revoke all on function public.cx_channel_thread_participant(varchar, varchar) from public" in source
    assert "grant select, insert on table public.cx_channel_threads, public.cx_channel_thread_members to ai_agent_runtime" in source
    assert "revoke update, delete on table public.cx_channel_threads, public.cx_channel_thread_members from ai_agent_runtime" in source
    assert "revoke all on table public.cx_channel_threads, public.cx_channel_thread_members from public" in source
    assert "cx_channel_thread_participant_snapshot_guard" in source
    assert "participant_principal_ids is immutable" in source
    snapshot_guard = _sql_function_definition(source, "cx_channel_thread_participant_snapshot_guard")
    enqueue = _sql_function_definition(source, "cx_enqueue_channel_deliveries")
    assert "return new;\nend;" in snapshot_guard
    assert "return inserted_count;\nend;" in enqueue


def test_frontend_dist_is_current_offline_shell():
    html = _source("shared/web/dist/index.html")
    javascript = _frontend_asset(".js")
    stylesheet = _frontend_asset(".css")
    assert "/static/assets/" in html
    assert re.search(r"/static/assets/index-[^\"']+\.js", html)
    assert re.search(r"/static/assets/index-[^\"']+\.css", html)
    assert "Runtime boundary" in javascript
    assert "cx-release-version" in stylesheet
    assert "v4.3.0" not in javascript and "v4.3.1" not in javascript
    assert "api/auth/login" in javascript
    assert "api/channels" in javascript
    assert "api/enrollment/grants" in javascript
    assert "animation:" in stylesheet and "@keyframes cx-spin" in stylesheet
