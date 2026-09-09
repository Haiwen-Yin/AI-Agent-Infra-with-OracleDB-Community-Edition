"""Database authoritative lifecycle for local built-in knowledge packages."""
from __future__ import annotations
import hashlib, json
import re
from typing import Any
from . import connection, identity_api

class KnowledgeLifecycleError(ValueError):
    pass

def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _chunks(package: dict[str, Any]) -> list[str]:
    text = json.dumps(package.get("content"), ensure_ascii=False, sort_keys=True)
    parts = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if item.strip()]
    return [" ".join(parts)[start:start + 1200] for start in range(0, len(" ".join(parts)), 1200)] or [text[:1200]]

def publish(actor: str, key: str, content: dict[str, Any], *, audience: str, scope_type: str,
            version: int, reason: str, dialect: str = "", edition: str = "") -> dict[str, Any]:
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required")
    if not key.strip() or key != key.strip() or len(key) > 128 or not isinstance(content, dict) or type(version) is not int or version < 1 or len(reason.strip()) < 3:
        raise KnowledgeLifecycleError("knowledge package metadata is invalid")
    if audience not in {"MANAGEMENT_AGENTS", "COMPLIANCE_ADMIN", "PUBLIC"} or scope_type not in {"PLATFORM_GLOBAL", "COMPLIANCE_AGENT", "PUBLIC"}:
        raise KnowledgeLifecycleError("knowledge package scope is invalid")
    if dialect not in {"", "oracle", "pg", "yashandb"} or edition not in {"", "community", "enterprise"}:
        raise KnowledgeLifecycleError("knowledge package compatibility is invalid")
    package = {"dialect": dialect, "edition": edition, "content": content,
               "audience": audience, "scope_type": scope_type}
    digest = _digest(package); knowledge_id = f"PK_LOCAL_{_digest({'key':key,'version':version})[:32]}"
    def work(tx):
        existing = tx.query_one("SELECT KNOWLEDGE_ID,CONTENT_DIGEST,STATUS FROM CX_PLATFORM_KNOWLEDGE WHERE KNOWLEDGE_KEY=:key AND VERSION=:version FOR UPDATE", {"key":key[:128],"version":version})
        if existing:
            row = {str(k).lower():v for k,v in existing.items()}
            if row.get("content_digest") != digest:
                raise KnowledgeLifecycleError("published knowledge version is immutable")
            return {"knowledge_id": row.get("knowledge_id"), "status": row.get("status"), "idempotent": True, "digest": digest}
        tx.execute("INSERT INTO CX_PLATFORM_KNOWLEDGE(KNOWLEDGE_ID,KNOWLEDGE_KEY,VERSION,KNOWLEDGE_KIND,AUDIENCE,SCOPE_TYPE,CLASSIFICATION,CONTENT_JSON,CONTENT_DIGEST,SIGNATURE,SIGNATURE_STATUS,STATUS,VALID_FROM,CREATED_BY) VALUES (:id,:key,:version,'BUILTIN_PACKAGE',:audience,:scope,'RESTRICTED',:content,:digest,:signature,'VERIFIED_BUILTIN','PUBLISHED',CURRENT_TIMESTAMP,:actor)", {"id":knowledge_id,"key":key,"version":version,"audience":audience,"scope":scope_type,"content":json.dumps(package,ensure_ascii=True,sort_keys=True),"digest":digest,"signature":"LOCAL-SHA256:"+digest,"actor":actor})
        for number, chunk in enumerate(_chunks(package), 1):
            tx.execute("INSERT INTO CX_PLATFORM_KNOWLEDGE_CHUNKS(CHUNK_ID,KNOWLEDGE_ID,CHUNK_NO,CHUNK_TEXT,CHUNK_DIGEST,AUDIENCE,SCOPE_TYPE,CLASSIFICATION,STATUS) VALUES (:chunk,:knowledge,:chunk_no,:text,:chunk_digest,:audience,:scope,'RESTRICTED','ACTIVE')", {"chunk": f"{knowledge_id}_C{number}", "knowledge": knowledge_id, "chunk_no": number, "text": chunk, "chunk_digest": hashlib.sha256(chunk.encode()).hexdigest(), "audience": audience, "scope": scope_type})
        identity_api._audit_tx(tx, actor, "BUILTIN_KNOWLEDGE_PUBLISH", "PLATFORM_KNOWLEDGE", knowledge_id, "ALLOW", reason)
        return {"knowledge_id":knowledge_id,"status":"PUBLISHED","idempotent":False,"digest":digest}
    return connection.execute_transaction_callback(work)

def withdraw(actor: str, knowledge_id: str, reason: str) -> dict[str, Any]:
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW" or len(reason.strip()) < 3:
        raise PermissionError("knowledge withdrawal denied")
    def work(tx):
        changed = tx.execute("UPDATE CX_PLATFORM_KNOWLEDGE SET STATUS='REVOKED',VALID_UNTIL=CURRENT_TIMESTAMP WHERE KNOWLEDGE_ID=:id AND STATUS='PUBLISHED'", {"id":knowledge_id})
        if changed != 1: raise KnowledgeLifecycleError("knowledge package is unavailable or already withdrawn")
        tx.execute("UPDATE CX_PLATFORM_KNOWLEDGE_CHUNKS SET STATUS='REVOKED' WHERE KNOWLEDGE_ID=:id AND STATUS='ACTIVE'", {"id":knowledge_id})
        identity_api._audit_tx(tx, actor, "BUILTIN_KNOWLEDGE_WITHDRAW", "PLATFORM_KNOWLEDGE", knowledge_id, "ALLOW", reason)
        return {"knowledge_id":knowledge_id,"status":"REVOKED"}
    return connection.execute_transaction_callback(work)

def list_packages(actor: str, limit: int = 100) -> list[dict[str, Any]]:
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW": raise PermissionError("platform management permission is required")
    suffix = " LIMIT :limit" if str(connection.DATABASE_DIALECT).lower() in {"pg","postgresql"} else " FETCH FIRST :limit ROWS ONLY"
    rows = connection.execute_query("SELECT KNOWLEDGE_ID,KNOWLEDGE_KEY,VERSION,AUDIENCE,SCOPE_TYPE,CONTENT_DIGEST,SIGNATURE_STATUS,STATUS,CREATED_AT,VALID_UNTIL FROM CX_PLATFORM_KNOWLEDGE WHERE KNOWLEDGE_KIND='BUILTIN_PACKAGE' ORDER BY KNOWLEDGE_KEY,VERSION DESC"+suffix,{"limit":max(1,min(limit,500))})
    return [{str(k).lower():v for k,v in row.items()} for row in rows]

def reindex_packages(actor: str, limit: int = 50) -> dict[str, int]:
    """Bounded, idempotent repair job for published packages missing chunks."""
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required")
    rows = connection.execute_query("SELECT KNOWLEDGE_ID,CONTENT_JSON,AUDIENCE,SCOPE_TYPE FROM CX_PLATFORM_KNOWLEDGE k WHERE k.KNOWLEDGE_KIND='BUILTIN_PACKAGE' AND k.STATUS='PUBLISHED' AND NOT EXISTS (SELECT 1 FROM CX_PLATFORM_KNOWLEDGE_CHUNKS c WHERE c.KNOWLEDGE_ID=k.KNOWLEDGE_ID) FETCH FIRST :limit ROWS ONLY", {"limit": max(1, min(int(limit), 100))})
    indexed = 0
    for raw in rows:
        row = {str(k).lower(): v for k, v in raw.items()}
        package = json.loads(str(row["content_json"]))
        for number, chunk in enumerate(_chunks(package), 1):
            connection.execute("INSERT INTO CX_PLATFORM_KNOWLEDGE_CHUNKS(CHUNK_ID,KNOWLEDGE_ID,CHUNK_NO,CHUNK_TEXT,CHUNK_DIGEST,AUDIENCE,SCOPE_TYPE,CLASSIFICATION,STATUS) VALUES (:chunk,:knowledge,:chunk_no,:text,:chunk_digest,:audience,:scope,'RESTRICTED','ACTIVE')", {"chunk": f"{row['knowledge_id']}_C{number}", "knowledge": row["knowledge_id"], "chunk_no": number, "text": chunk, "chunk_digest": hashlib.sha256(chunk.encode()).hexdigest(), "audience": row["audience"], "scope": row["scope_type"]})
        indexed += 1
    return {"scanned": len(rows), "indexed": indexed}
