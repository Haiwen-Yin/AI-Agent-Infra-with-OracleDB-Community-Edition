"""AI Agent Infra v4.0.0 - Rich Test Data Seeder

Seeds 50+ entities with embeddings, edges, tags, and metadata across MEMORY/KNOWLEDGE/SPEC types.
Designed to validate multi-signal hybrid search (vector + keyword + relational + graph).
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import (
    memory_api, knowledge_api, spec_api, embedding_api,
    graph_api, agent_api, workspace_api, collab_api,
)
from lib.connection import execute, execute_query

DOMAINS = {
    "database": [
        ("Database Partitioning Strategies", "Oracle LIST and RANGE composite partitioning for scalable entity storage with automatic data pruning and subpartition templates", "architecture", 9),
        ("Index Optimization for Vector Search", "Bitmap and B-tree index strategies for VECTOR_DISTANCE queries on ENTITY_EMBEDDINGS with cosine similarity metrics", "performance", 8),
        ("JSON-Relational Duality Views", "JRD updatable views enabling document API on relational tables with etag-based optimistic concurrency control in Oracle AI Database 26ai", "architecture", 9),
        ("Connection Pool Configuration", "oracledb thin mode connection pool tuning: pool_min, pool_max, pool_increment parameters for high-concurrency workloads", "operations", 6),
        ("Oracle VECTOR Data Type", "Native VECTOR column storage with TO_VECTOR conversion, VECTOR_DISTANCE metrics (COSINE, EUCLIDEAN, DOT_PRODUCT, MANHATTAN) and dimension constraints", "database", 9),
        ("SQL Property Graph Queries", "GRAPH_TABLE SQL operator for graph pattern matching in ORACLE_MEMORY_GRAPH with vertex/edge filters and path traversal", "database", 8),
        ("Scheduler Job Management", "DBMS_SCHEDULER for automated maintenance: memory fusion, session cleanup, embedding generation, dormant agent detection", "operations", 5),
    ],
    "security": [
        ("SHA256 Password Hashing", "PBKDF2-HMAC-SHA256 with 100000 iterations for SYSTEM_USERS authentication, SHA256: prefix convention and secure comparison", "security", 9),
        ("Reversible Encryption for Credentials", "PBKDF2 key derivation with XOR cipher and length-prefix encoding for AGENT_CREDENTIALS, supporting key rotation without data loss", "security", 8),
        ("Data Masking Service", "Context-aware data masking with 7 regex patterns (email, phone, credit_card, ssn, api_key, ip_address, jwt_token) and 4 sensitivity levels", "security", 7),
        ("ACL Configuration for UTL_HTTP", "Oracle ACL setup for EMBEDDING_MANAGER UTL_HTTP access to external embedding API endpoints with proper privilege grants", "security", 8),
        ("Session-Based Authentication", "Web visualization session management with 5-min auto-logout, SHA256 verification, and configurable lockout policies", "security", 6),
    ],
    "ml": [
        ("BGE-M3 Embedding Model", "BAAI bge-m3 multilingual embedding model producing 1024-dimensional vectors via OpenAI-compatible API at text-embedding-bge-m3", "ml", 8),
        ("Embedding Dimension Detection", "Auto-detection of embedding model dimensions using MODEL_DIMENSIONS lookup table with live API probe fallback for unknown models", "ml", 7),
        ("Batch Embedding Generation", "EMBEDDING_MANAGER.batch_embed_entities for bulk vector generation on unembedded entities with configurable entity type and limit parameters", "ml", 7),
        ("Vector Similarity Search Optimization", "Cosine similarity search using VECTOR_DISTANCE with FETCH FIRST N for efficient top-k retrieval on partitioned ENTITY_EMBEDDINGS", "performance", 8),
        ("Hybrid Retrieval: Vector + Keyword", "Multi-signal retrieval combining vector similarity (VECTOR_DISTANCE) with SQL keyword matching (LIKE) using weighted scoring for reranking", "ml", 9),
    ],
    "architecture": [
        ("Unified Entity Architecture", "Single ENTITIES table with ENTITY_TYPE discriminator replacing 5 separate tables, enabling cross-type queries and unified JRD views", "architecture", 10),
        ("Reference Partitioning for Child Tables", "6 reference-partitioned child tables (ENTITY_EDGES, KNOWLEDGE_META, SPEC_META, HARNESS_META, ENTITY_EMBEDDINGS, ENTITY_TAGS) inheriting partition key from ENTITIES", "architecture", 9),
        ("Agent Elastic Management", "DORMANT and POOL agent states for resource optimization: DORMANT preserves context, POOL is stateless with skills_tags matching for user assignment", "architecture", 8),
        ("Spec Driven Development Pattern", "SPEC entity subtype with SPEC_META reference-partitioned metadata and SPEC_PLAN_LINKS many-to-many relationship enabling DRIVES/VALIDATES/CONSTRAINS/EXTENDS linkage", "architecture", 9),
        ("Collaboration Group Model", "Mode C collaboration with COLLAB_GROUPS shared workspace and COLLAB_GROUP_MEMBERS personal workspaces for LEAD/CONTRIBUTOR roles", "architecture", 8),
        ("Workspace Context Continuity", "Append-only WORKSPACE_CONTEXT chain (CHECKPOINT, HANDOFF, SUMMARY, ERROR_STATE, AUTO_SAVE) with PREDECESSOR_SESSION_ID for agent handoff", "architecture", 8),
        ("Composite Primary Key Design", "Composite PKs (ENTITY_ID, ENTITY_TYPE) on ENTITIES with global unique constraints for cross-partition FK references and JRD updatable views", "architecture", 9),
    ],
    "methodology": [
        ("Memory Fusion Engine", "Automated memory lifecycle: fuse_similar_memories combines duplicates, decay_memories reduces importance over time, archive_old_memories prunes below threshold", "methodology", 7),
        ("Knowledge Validation Pipeline", "KNOWLEDGE_BASE_API.validate_knowledge with domain expert review, contradiction detection, and resolution workflow for knowledge integrity", "methodology", 8),
        ("Agent Permission Model", "Hierarchical permission system with AGENT_PERMISSION_MANAGER: grant/revoke/check with audit trail in AGENT_PERMISSION_LOG", "methodology", 7),
        ("Harness Template System", "Reusable agent execution blueprints with variable substitution, DERIVES_FROM inheritance, 5 built-in tool sets, and lifecycle management (DRAFT→PUBLISHED→ARCHIVED)", "methodology", 6),
    ],
}


def seed_entities():
    created = {"memory": 0, "knowledge": 0, "spec": 0}
    entity_map = {}

    for domain, items in DOMAINS.items():
        for title, content, category, importance in items:
            mid = memory_api.create_memory(
                title=title,
                content=content,
                category=category,
                importance=importance,
            )
            created["memory"] += 1
            entity_map[title] = {"id": mid, "type": "MEMORY", "domain": domain}

            kid = knowledge_api.create_knowledge(
                title=title,
                domain=domain,
                topic=domain,
                content=content,
            )
            created["knowledge"] += 1
            entity_map[f"KN:{title}"] = {"id": kid, "type": "KNOWLEDGE", "domain": domain}

    specs = [
        ("Database Architecture Specification", "v1.2", "APPROVED", "database", '["Scalable partitioning","JRD duality views","Vector search integration"]', "HIGH"),
        ("Security Framework Specification", "v2.0", "IN_REVIEW", "security", '["PBKDF2 encryption","ACL management","Session authentication"]', "CRITICAL"),
        ("Embedding Service Specification", "v1.0", "DRAFT", "ml", '["Multi-model support","Auto dimension detection","Batch generation"]', "MEDIUM"),
        ("Agent Lifecycle Specification", "v1.1", "APPROVED", "architecture", '["Elastic states","Credential management","Pool assignment"]', "HIGH"),
        ("Hybrid Search Specification", "v0.9", "DRAFT", "architecture", '["4-signal fusion","Weighted scoring","Cross-type retrieval"]', "HIGH"),
    ]
    for title, version, status, domain, criteria, complexity in specs:
        sid = spec_api.create_spec(
            title=title,
            content=f"Specification for {domain} subsystem",
            category=f"{domain}-spec",
            importance=9,
            spec_scope=domain,
            complexity=complexity,
            acceptance_criteria=criteria,
        )
        created["spec"] += 1
        entity_map[f"SP:{title}"] = {"id": sid, "type": "SPEC", "domain": domain}

    print(f"Created: {created['memory']} memories, {created['knowledge']} knowledge, {created['spec']} specs")
    return entity_map


def seed_edges(entity_map):
    edge_count = 0
    cross_domain_pairs = [
        ("Database Partitioning Strategies", "Index Optimization for Vector Search", "RELATED_TO"),
        ("Database Partitioning Strategies", "Reference Partitioning for Child Tables", "SUPPORTS"),
        ("Database Partitioning Strategies", "Composite Primary Key Design", "SUPPORTS"),
        ("SHA256 Password Hashing", "Reversible Encryption for Credentials", "RELATED_TO"),
        ("SHA256 Password Hashing", "Session-Based Authentication", "SUPPORTS"),
        ("BGE-M3 Embedding Model", "Embedding Dimension Detection", "SUPPORTS"),
        ("BGE-M3 Embedding Model", "Batch Embedding Generation", "SUPPORTS"),
        ("BGE-M3 Embedding Model", "Vector Similarity Search Optimization", "SUPPORTS"),
        ("Unified Entity Architecture", "Reference Partitioning for Child Tables", "EXPLAINS"),
        ("Unified Entity Architecture", "Composite Primary Key Design", "EXPLAINS"),
        ("Unified Entity Architecture", "JSON-Relational Duality Views", "SUPPORTS"),
        ("Agent Elastic Management", "Agent Lifecycle Specification", "APPLIES_TO"),
        ("Spec Driven Development Pattern", "Database Architecture Specification", "APPLIES_TO"),
        ("Hybrid Retrieval: Vector + Keyword", "Vector Similarity Search Optimization", "SUPPORTS"),
        ("Hybrid Retrieval: Vector + Keyword", "BGE-M3 Embedding Model", "USES"),
        ("Knowledge Validation Pipeline", "Memory Fusion Engine", "RELATED_TO"),
        ("Reversible Encryption for Credentials", "ACL Configuration for UTL_HTTP", "RELATED_TO"),
        ("Workspace Context Continuity", "Agent Elastic Management", "SUPPORTS"),
        ("Collaboration Group Model", "Workspace Context Continuity", "SUPPORTS"),
        ("Embedding Dimension Detection", "Oracle VECTOR Data Type", "SUPPORTS"),
    ]

    for src_title, tgt_title, edge_type in cross_domain_pairs:
        src = entity_map.get(src_title)
        tgt = entity_map.get(tgt_title)
        if src and tgt:
            try:
                knowledge_api.add_edge(src["id"], "MEMORY", tgt["id"], edge_type, 0.8)
                edge_count += 1
            except Exception:
                pass
        src_k = entity_map.get(f"KN:{src_title}")
        tgt_k = entity_map.get(f"KN:{tgt_title}")
        if src_k and tgt_k:
            try:
                knowledge_api.add_edge(src_k["id"], "KNOWLEDGE", tgt_k["id"], edge_type, 0.8)
                edge_count += 1
            except Exception:
                pass

    print(f"Created {edge_count} edges")


def seed_tags(entity_map):
    from lib.connection import get_connection
    tag_data = {
        "partitioning": ["Database Partitioning Strategies", "Reference Partitioning for Child Tables", "Composite Primary Key Design"],
        "vector": ["Oracle VECTOR Data Type", "BGE-M3 Embedding Model", "Vector Similarity Search Optimization", "Hybrid Retrieval: Vector + Keyword"],
        "encryption": ["SHA256 Password Hashing", "Reversible Encryption for Credentials", "ACL Configuration for UTL_HTTP"],
        "JRD": ["JSON-Relational Duality Views", "Unified Entity Architecture"],
        "agent": ["Agent Elastic Management", "Agent Lifecycle Specification", "Collaboration Group Model"],
        "search": ["Vector Similarity Search Optimization", "Hybrid Retrieval: Vector + Keyword", "SQL Property Graph Queries"],
        "performance": ["Index Optimization for Vector Search", "Vector Similarity Search Optimization", "Connection Pool Configuration"],
        "graph": ["SQL Property Graph Queries", "Unified Entity Architecture"],
    }
    tag_count = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for tag_name, titles in tag_data.items():
                for title in titles:
                    entity = entity_map.get(title)
                    if not entity:
                        continue
                    try:
                        cur.execute("MERGE INTO TAGS t USING (SELECT :tn AS tn FROM dual) s ON (t.TAG_NAME = s.tn) WHEN NOT MATCHED THEN INSERT (TAG_ID, TAG_NAME) VALUES (TAGS_SEQ.NEXTVAL, :tn)", {"tn": tag_name})
                        cur.execute("SELECT TAG_ID FROM TAGS WHERE TAG_NAME = :tn", {"tn": tag_name})
                        tid = cur.fetchone()[0]
                        cur.execute("MERGE INTO ENTITY_TAGS et USING (SELECT :eid AS eid, :tid AS tid, :etype AS etype FROM dual) s ON (et.ENTITY_ID = s.eid AND et.TAG_ID = s.tid AND et.ENTITY_TYPE = s.etype) WHEN NOT MATCHED THEN INSERT (ENTITY_ID, ENTITY_TYPE, TAG_ID) VALUES (:eid, :etype, :tid)", {"eid": entity["id"], "etype": entity["type"], "tid": int(tid)})
                        conn.commit()
                        tag_count += 1
                    except Exception as e:
                        conn.rollback()
                        print(f"  Tag error: {tag_name}/{title[:30]}: {e}")
    print(f"Created {tag_count} tag associations")


def seed_embeddings(entity_map):
    count = 0
    failed = 0
    items = list(entity_map.items())
    for i, (title, info) in enumerate(items):
        text = title.replace("KN:", "").replace("SP:", "")
        try:
            ok = embedding_api.store_embedding(info["id"], info["type"], text)
            if ok:
                count += 1
            else:
                failed += 1
            if (i + 1) % 10 == 0:
                print(f"  Embedded {i+1}/{len(items)} ({count} ok, {failed} failed)")
                time.sleep(1)
        except Exception as e:
            failed += 1
            print(f"  Failed: {title[:40]}: {e}")
    print(f"Embeddings: {count} ok, {failed} failed out of {len(items)}")


def main():
    print("=" * 60)
    print("AI Agent Infra v4.0.0 - Rich Test Data Seeder")
    print("=" * 60)

    print("\n--- Phase 1: Create Entities ---")
    entity_map = seed_entities()

    print("\n--- Phase 2: Create Edges ---")
    seed_edges(entity_map)

    print("\n--- Phase 3: Create Tags ---")
    seed_tags(entity_map)

    print("\n--- Phase 4: Generate Embeddings ---")
    seed_embeddings(entity_map)

    print("\n--- Done ---")


if __name__ == "__main__":
    main()
