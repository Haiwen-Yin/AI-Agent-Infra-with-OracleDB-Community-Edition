"""AI Agent Infra v3.6.1 - Community Edition - Unified Configuration Manager

Reads from config.json with environment variable overrides.
Priority: Environment Variables > config.json > Built-in defaults
Supports Admin/Agent separation modes (standalone, admin, agent).
"""

import json
import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class DatabaseConfig:
    user: str = "openclaw"
    password: str = "hermes"
    dsn: str = "10.10.10.130:1521/openclaw"
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
    api_url: str = "http://10.10.10.1:12345/v1/embeddings"
    model: str = "text-embedding-bge-m3"
    dimension: int = 1024


@dataclass(frozen=True)
class SecurityConfig:
    masking_enabled: bool = True
    pbkdf2_iterations: int = 100000
    max_login_attempts: int = 5
    lockout_minutes: int = 15


@dataclass(frozen=True)
class AgentModeConfig:
    mode: str = "standalone"
    admin_token: Optional[str] = None
    admin_api_url: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass(frozen=True)
class Config:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    agent: AgentModeConfig = field(default_factory=AgentModeConfig)
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

    db_resolved = _decrypt_database_section(db_raw)

    db = DatabaseConfig(
        user=os.environ.get("MEMORY_DB_USER", db_resolved.get("user", DatabaseConfig.user)),
        password=os.environ.get("MEMORY_DB_PASSWORD", db_resolved.get("password", DatabaseConfig.password)),
        dsn=os.environ.get("MEMORY_DB_DSN", db_resolved.get("dsn", DatabaseConfig.dsn)),
        pool_min=int(db_resolved.get("pool_min", DatabaseConfig.pool_min)),
        pool_max=int(db_resolved.get("pool_max", DatabaseConfig.pool_max)),
        pool_increment=int(db_resolved.get("pool_increment", DatabaseConfig.pool_increment)),
        _encrypted=db_raw.get("_encrypted"),
        _key_source=db_raw.get("_key_source"),
    )

    srv = ServerConfig(
        host=os.environ.get("MEMORY_SERVER_HOST", srv_raw.get("host", ServerConfig.host)),
        port=int(os.environ.get("MEMORY_SERVER_PORT", srv_raw.get("port", ServerConfig.port))),
        session_timeout=int(os.environ.get("MEMORY_SESSION_TIMEOUT", srv_raw.get("session_timeout", ServerConfig.session_timeout))),
    )

    emb = EmbeddingConfig(
        api_url=os.environ.get("MEMORY_EMBEDDING_API", emb_raw.get("api_url", EmbeddingConfig.api_url)),
        model=emb_raw.get("model", EmbeddingConfig.model),
        dimension=int(emb_raw.get("dimension", EmbeddingConfig.dimension)),
    )

    sec = SecurityConfig(
        masking_enabled=sec_raw.get("masking_enabled", SecurityConfig.masking_enabled),
        pbkdf2_iterations=int(sec_raw.get("pbkdf2_iterations", SecurityConfig.pbkdf2_iterations)),
        max_login_attempts=int(sec_raw.get("max_login_attempts", SecurityConfig.max_login_attempts)),
        lockout_minutes=int(sec_raw.get("lockout_minutes", SecurityConfig.lockout_minutes)),
    )

    agent_raw = raw.get("agent", {})
    agt = AgentModeConfig(
        mode=os.environ.get("AGENT_MODE", agent_raw.get("mode", AgentModeConfig.mode)),
        admin_token=os.environ.get("AGENT_ADMIN_TOKEN", agent_raw.get("admin_token", AgentModeConfig.admin_token)),
        admin_api_url=os.environ.get("AGENT_ADMIN_API_URL", agent_raw.get("admin_api_url", AgentModeConfig.admin_api_url)),
        agent_id=os.environ.get("AGENT_ID", agent_raw.get("agent_id", AgentModeConfig.agent_id)),
    )

    return Config(database=db, server=srv, embedding=emb, security=sec, agent=agt, project_root=_PROJECT_ROOT)


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
