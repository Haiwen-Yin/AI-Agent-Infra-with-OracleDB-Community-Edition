"""AI Agent Infra v3.10.1 - Community Edition - Unified Configuration Manager

Reads from encrypted config.json with environment variable fallback.
Supports encrypted database credentials, LDAP configuration, and enterprise features.
Admin/Agent separation modes (standalone, admin, agent).
Priority: config.json (encrypted) > Environment Variables > Built-in defaults
"""

import json
import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

VERSION = "3.10.1"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class DatabaseConfig:
    user: str = "aiadmin"
    password: str = "oracle"
    dsn: str = "localhost:1521/free"
    pool_min: int = 2
    pool_max: int = 5
    pool_increment: int = 1
    _encrypted: Optional[str] = None
    _key_source: Optional[str] = None


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    session_timeout: int = 300


@dataclass(frozen=True)
class EmbeddingConfig:
    api_url: str = ""
    model: str = ""
    dimension: int = 0


@dataclass(frozen=True)
class SecurityConfig:
    masking_enabled: bool = True
    pbkdf2_iterations: int = 210000
    max_login_attempts: int = 5
    lockout_minutes: int = 15


@dataclass(frozen=True)
class AgentModeConfig:
    mode: str = "standalone"
    admin_token: Optional[str] = None
    admin_api_url: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass(frozen=True)
class LdapConfig:
    enabled: bool = False
    server_url: str = ""
    base_dn: str = ""
    bind_dn: str = ""
    bind_password_encrypted: str = ""
    user_filter: str = "(uid={username})"
    group_filter: str = "(memberUid={username})"
    sync_interval_min: int = 60
    tls: bool = True
    tls_validate: bool = True


@dataclass(frozen=True)
class EnterpriseConfig:
    license_type: str = "ENTERPRISE"
    skill_token_ttl_min: int = 5
    audit_threshold_score: int = 40
    audit_idle_timeout_min: int = 60
    audit_log_retention_days: int = 90
    presigned_url_ttl_sec: int = 300


@dataclass(frozen=True)
class LLMConfig:
    api_url: str = ""
    api_key: str = ""
    model: str = ""
    max_context: int = 500000
    stream_enabled: bool = True


@dataclass(frozen=True)
class ModelRoutingConfig:
    simple_model: str = ""
    simple_api_url: str = ""
    simple_api_key: str = ""
    standard_model: str = ""
    standard_api_url: str = ""
    standard_api_key: str = ""
    complex_model: str = ""
    complex_api_url: str = ""
    complex_api_key: str = ""
    eval_threshold: float = 0.8
    token_budget: int = 2000


@dataclass(frozen=True)
class MCPConfig:
    enabled: bool = False
    transport: str = "stdio"
    sse_port: int = 9000
    exposed_tools: tuple = (
        "search", "memory_create", "memory_search",
        "knowledge_create", "knowledge_search",
        "tool_list", "tool_invoke", "graph_neighbors",
        "loop_status", "agent_list",
    )


@dataclass(frozen=True)
class Config:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    ldap: LdapConfig = field(default_factory=LdapConfig)
    enterprise: EnterpriseConfig = field(default_factory=EnterpriseConfig)
    agent: AgentModeConfig = field(default_factory=AgentModeConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    model_routing: ModelRoutingConfig = field(default_factory=ModelRoutingConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    project_root: Path = field(default_factory=lambda: _PROJECT_ROOT)


def _load_config_file() -> dict:
    config_path = _PROJECT_ROOT / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _decrypt_database_section(db_raw: dict) -> dict:
    encrypted_blob = db_raw.get("_encrypted")
    if not encrypted_blob:
        return db_raw
    try:
        from .connection_crypto import decrypt_section
        decrypted = decrypt_section(encrypted_blob)
        merged = dict(db_raw)
        for k, v in decrypted.items():
            if k not in ("_encrypted", "_key_source"):
                merged[k] = v
        return merged
    except Exception as e:
        logger.error("Failed to decrypt database config: %s", e)
        return db_raw


def load_config() -> Config:
    raw = _load_config_file()

    db_raw = raw.get("database", {})
    srv_raw = raw.get("server", {})
    emb_raw = raw.get("embedding", {})
    sec_raw = raw.get("security", {})
    ldap_raw = raw.get("ldap", {})
    ent_raw = raw.get("enterprise", {})

    db_resolved = _decrypt_database_section(db_raw)

    # Priority: config.json (decrypted) > Environment Variables > Defaults
    db = DatabaseConfig(
        user=db_resolved.get("user") or os.environ.get("MEMORY_DB_USER", DatabaseConfig.user),
        password=db_resolved.get("password") or os.environ.get("MEMORY_DB_PASSWORD", DatabaseConfig.password),
        dsn=db_resolved.get("dsn") or os.environ.get("MEMORY_DB_DSN", DatabaseConfig.dsn),
        pool_min=int(db_resolved.get("pool_min", DatabaseConfig.pool_min)),
        pool_max=int(db_resolved.get("pool_max", DatabaseConfig.pool_max)),
        pool_increment=int(db_resolved.get("pool_increment", DatabaseConfig.pool_increment)),
        _encrypted=db_raw.get("_encrypted"),
        _key_source=db_raw.get("_key_source"),
    )

    srv = ServerConfig(
        host=srv_raw.get("host") or os.environ.get("MEMORY_SERVER_HOST", ServerConfig.host),
        port=int(srv_raw.get("port") or os.environ.get("MEMORY_SERVER_PORT", ServerConfig.port)),
        session_timeout=int(srv_raw.get("session_timeout") or os.environ.get("MEMORY_SESSION_TIMEOUT", ServerConfig.session_timeout)),
    )

    emb = EmbeddingConfig(
        api_url=emb_raw.get("api_url") or os.environ.get("MEMORY_EMBEDDING_API", EmbeddingConfig.api_url),
        model=emb_raw.get("model") or os.environ.get("MEMORY_EMBEDDING_MODEL", EmbeddingConfig.model),
        dimension=int(emb_raw.get("dimension") or os.environ.get("MEMORY_EMBEDDING_DIM", EmbeddingConfig.dimension)),
    )

    sec = SecurityConfig(
        masking_enabled=sec_raw.get("masking_enabled", SecurityConfig.masking_enabled),
        pbkdf2_iterations=int(sec_raw.get("pbkdf2_iterations", SecurityConfig.pbkdf2_iterations)),
        max_login_attempts=int(sec_raw.get("max_login_attempts", SecurityConfig.max_login_attempts)),
        lockout_minutes=int(sec_raw.get("lockout_minutes", SecurityConfig.lockout_minutes)),
    )

    ldap = LdapConfig(
        enabled=ldap_raw.get("enabled", LdapConfig.enabled),
        server_url=ldap_raw.get("server_url") or os.environ.get("LDAP_SERVER_URL", LdapConfig.server_url),
        base_dn=ldap_raw.get("base_dn") or os.environ.get("LDAP_BASE_DN", LdapConfig.base_dn),
        bind_dn=ldap_raw.get("bind_dn") or os.environ.get("LDAP_BIND_DN", LdapConfig.bind_dn),
        bind_password_encrypted=ldap_raw.get("bind_password_encrypted", LdapConfig.bind_password_encrypted),
        user_filter=ldap_raw.get("user_filter", LdapConfig.user_filter),
        group_filter=ldap_raw.get("group_filter", LdapConfig.group_filter),
        sync_interval_min=int(ldap_raw.get("sync_interval_min", LdapConfig.sync_interval_min)),
        tls=ldap_raw.get("tls", LdapConfig.tls),
        tls_validate=ldap_raw.get("tls_validate", LdapConfig.tls_validate),
    )

    ent = EnterpriseConfig(
        license_type=ent_raw.get("license_type", EnterpriseConfig.license_type),
        skill_token_ttl_min=int(ent_raw.get("skill_token_ttl_min", EnterpriseConfig.skill_token_ttl_min)),
        audit_threshold_score=int(ent_raw.get("audit_threshold_score", EnterpriseConfig.audit_threshold_score)),
        audit_idle_timeout_min=int(ent_raw.get("audit_idle_timeout_min", EnterpriseConfig.audit_idle_timeout_min)),
        audit_log_retention_days=int(ent_raw.get("audit_log_retention_days", EnterpriseConfig.audit_log_retention_days)),
        presigned_url_ttl_sec=int(ent_raw.get("presigned_url_ttl_sec", EnterpriseConfig.presigned_url_ttl_sec)),
    )

    agent_raw = raw.get("agent", {})
    agt = AgentModeConfig(
        mode=agent_raw.get("mode") or os.environ.get("AGENT_MODE", AgentModeConfig.mode),
        admin_token=agent_raw.get("admin_token") or os.environ.get("AGENT_ADMIN_TOKEN", AgentModeConfig.admin_token),
        admin_api_url=agent_raw.get("admin_api_url") or os.environ.get("AGENT_ADMIN_API_URL", AgentModeConfig.admin_api_url),
        agent_id=agent_raw.get("agent_id") or os.environ.get("AGENT_ID", AgentModeConfig.agent_id),
    )

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        api_url=llm_raw.get("api_url") or os.environ.get("LLM_API_URL", LLMConfig.api_url),
        api_key=llm_raw.get("api_key") or os.environ.get("LLM_API_KEY", LLMConfig.api_key),
        model=llm_raw.get("model") or os.environ.get("LLM_MODEL", LLMConfig.model),
        max_context=int(llm_raw.get("max_context", LLMConfig.max_context)),
        stream_enabled=bool(llm_raw.get("stream_enabled", LLMConfig.stream_enabled)),
    )

    mr_raw = raw.get("model_routing", {})
    model_routing = ModelRoutingConfig(
        simple_model=mr_raw.get("simple_model", ModelRoutingConfig.simple_model),
        simple_api_url=mr_raw.get("simple_api_url", ModelRoutingConfig.simple_api_url),
        simple_api_key=mr_raw.get("simple_api_key", ModelRoutingConfig.simple_api_key),
        standard_model=mr_raw.get("standard_model", ModelRoutingConfig.standard_model),
        standard_api_url=mr_raw.get("standard_api_url", ModelRoutingConfig.standard_api_url),
        standard_api_key=mr_raw.get("standard_api_key", ModelRoutingConfig.standard_api_key),
        complex_model=mr_raw.get("complex_model", ModelRoutingConfig.complex_model),
        complex_api_url=mr_raw.get("complex_api_url", ModelRoutingConfig.complex_api_url),
        complex_api_key=mr_raw.get("complex_api_key", ModelRoutingConfig.complex_api_key),
        eval_threshold=float(mr_raw.get("eval_threshold", ModelRoutingConfig.eval_threshold)),
        token_budget=int(mr_raw.get("token_budget", ModelRoutingConfig.token_budget)),
    )

    mcp_raw = raw.get("mcp", {})
    mcp = MCPConfig(
        enabled=bool(mcp_raw.get("enabled", MCPConfig.enabled)),
        transport=mcp_raw.get("transport", MCPConfig.transport),
        sse_port=int(mcp_raw.get("sse_port", MCPConfig.sse_port)),
        exposed_tools=tuple(mcp_raw.get("exposed_tools", list(MCPConfig.exposed_tools))),
    )

    return Config(database=db, server=srv, embedding=emb, security=sec, ldap=ldap, enterprise=ent, agent=agt, llm=llm, model_routing=model_routing, mcp=mcp, project_root=_PROJECT_ROOT)


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
