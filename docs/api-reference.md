# API Reference - AI Agent Infra v4.0.1

## v4.0.1 Authentication Contract

`/api/health`, login, and explicit bootstrap endpoints are public. Other API
and MCP operations require an authenticated session or Bearer identity;
administrative operations also require the Admin role. Acting Agent identity
comes from the authenticated context, not a body or query `agent_id`.

## Execution Control API

```python
enqueue_job(job_type, agent_id, payload, idempotency_key, requires_approval, max_attempts) -> dict
get_job(job_id) -> dict | None
decide_job(job_id, approved, decided_by, reason) -> bool
cancel_job(job_id, requested_by) -> bool
claim_job(worker_id, lease_seconds) -> dict | None
renew_lease(job_id, lease_token, lease_seconds) -> bool
complete_job(job_id, lease_token, result) -> bool
fail_job(job_id, lease_token, error, retryable) -> bool
run_worker_once(worker_id) -> dict | None
```

Side-effect endpoints return a durable job ID and current approval/execution
state. The web request does not run an arbitrary command or HTTP call inline.

## Skill Package API

```python
discover_skills(agent_id, skill_type, runtime, keyword, limit) -> list
acquire_skill_text(skill_id) -> dict | None
acquire_skill_full(skill_id, agent_id, session_id) -> dict | None
materialize_skill(skill_id, install_root) -> dict | None
```

An uploaded ZIP must contain `SKILL.md`. Versions are immutable; complete
Markdown, nested paths, package SHA-256, and per-file SHA-256 values are
preserved. Materialization verifies the installed tree and writes read-only
files/directories. Equivalent authenticated operations are exposed through
MCP Skill tools.

## Python API (scripts/lib/)

## Python API (scripts/lib/)

### memory_api.py

```python
create_memory(title, content, category, importance, summary, source_agent, owned_by_agent, visibility) -> str
get_memory(entity_id) -> dict | None
update_memory(entity_id, **kwargs) -> bool
delete_memory(entity_id) -> bool
search_memories(keyword, category, visibility, owned_by_agent, limit, offset) -> list
get_agent_memories(agent_id, limit) -> list
count_memories(category) -> int
add_memory_tags(entity_id, tag_names) -> int
get_memory_tags(entity_id) -> list
remove_memory_tag(entity_id, tag_id) -> bool
```

- `entity_id` is `str` (VARCHAR2(64) via RAWTOHEX(SYS_GUID()))
- `title` replaces v2.0 `name`; `importance` replaces `priority` (1-10)
- Removed: `metadata`, `accessible_to`, `tags` (JSON) — use ENTITY_TAGS table
- Added: `summary`, `source_agent`, `retrieval_count` fields on return dicts

### knowledge_api.py

```python
create_knowledge(title, content, domain, topic, difficulty, category, importance, summary, owned_by_agent, visibility) -> str
get_knowledge(entity_id) -> dict | None
update_knowledge(entity_id, **kwargs) -> bool
delete_knowledge(entity_id) -> bool
search_knowledge(domain, topic, keyword, difficulty, limit, offset) -> list
get_due_reviews(limit) -> list
record_review(entity_id) -> bool
add_edge(source_id, source_type, target_id, edge_type, strength, confidence, metadata) -> str
get_edges(entity_id, direction) -> list
count_knowledge(domain) -> int
add_knowledge_tags(entity_id, tag_names) -> int
get_knowledge_tags(entity_id) -> list
remove_knowledge_tag(entity_id, tag_id) -> bool
```

- `add_edge` now requires `source_type` parameter (composite FK)
- Edge IDs prefixed with `E_`: `'E_' || RAWTOHEX(SYS_GUID())`
- `source_type` is the ENTITY_TYPE of the source entity (e.g., 'KNOWLEDGE', 'MEMORY')
- KNOWLEDGE_META fields: domain, topic, difficulty, review_count, last_reviewed, next_review
- Spaced review: `NEXT_REVIEW = SYSTIMESTAMP + LEAST(POWER(2, REVIEW_COUNT + 1), 30)`

### graph_api.py

```python
get_neighbors(entity_id, direction, edge_type, min_strength, limit) -> list
get_reachable(entity_id, max_hops, edge_type, limit) -> list
get_shortest_path(source_id, target_id, max_hops) -> list | None
find_similar_entities(entity_id, max_hops, limit) -> list
get_entity_context(entity_id, depth) -> dict
get_graph_stats() -> dict
get_subgraph(entity_ids, include_intermediate) -> dict
find_communities(entity_type, min_connections, limit) -> list
graph_search(keyword, entity_type, category, min_importance, limit) -> list
```

All functions use the `GRAPH_TABLE` SQL operator against `ORACLE_MEMORY_GRAPH`:

| Function | GRAPH_TABLE Pattern | Use Case |
|----------|-------------------|----------|
| `get_neighbors` | `MATCH (a)-[e]->(b)` or `MATCH (a)<-[e]-(b)` | One-hop adjacency |
| `get_reachable` | `MATCH (a)-[e]->{1,N}(v)` | Multi-hop reachability |
| `get_shortest_path` | `MATCH (a)-[e1]->(v1)-[e2]->...(vn)` | Path finding (max 6 hops) |
| `find_similar_entities` | `MATCH (a)-[e]->{1,N}(v)` | Graph-proximity similarity |
| `get_entity_context` | Direct SQL + `get_neighbors` | Full entity context with grouped neighbors |
| `get_graph_stats` | Direct SQL on ENTITIES/ENTITY_EDGES | Graph statistics and distributions |
| `get_subgraph` | Direct SQL with IN-list | Subgraph extraction with optional intermediate nodes |
| `find_communities` | Direct SQL with JOIN | Highly-connected entity clusters |
| `graph_search` | `MATCH (a) WHERE ...` | Graph-aware search with filtering |

### agent_api.py

```python
register_agent(agent_id, agent_name, agent_type, description, capabilities, config) -> str
get_agent(agent_id) -> dict | None
update_agent(agent_id, **kwargs) -> bool
decommission_agent(agent_id) -> bool
heartbeat(agent_id) -> bool
create_session(agent_id, wm_entity_id, context, owner_user_id, workspace_id, predecessor_session_id) -> str
end_session(session_id) -> bool
checkpoint_session(session_id, context_data) -> bool
get_session_chain(session_id, limit) -> list
get_active_sessions(agent_id) -> list
log_access(agent_id, entity_id, access_type, session_id) -> str
get_access_log(entity_id, agent_id, limit) -> list
create_collaboration(source_agent_id, target_agent_id, col_type, entity_id, context, strength) -> str
get_collaborations(agent_id, limit) -> list
```

- Session IDs: `'SES_' || RAWTOHEX(SYS_GUID())`
- Access log IDs: `'LOG_' || RAWTOHEX(SYS_GUID())`
- Collaboration IDs: `'COL_' || RAWTOHEX(SYS_GUID())`
- AGENT_SESSION is partitioned (LIST+RANGE), ROW MOVEMENT enabled
- AGENT_COLLABORATION has STRENGTH (0-1) field
- `create_session` new parameters: `owner_user_id` (session owner), `workspace_id` (workspace binding), `predecessor_session_id` (handoff chain)
- `checkpoint_session`: Saves a CHECKPOINT context to the session's workspace via `workspace_api.save_context()`
- `get_session_chain`: Traverses PREDECESSOR_SESSION_ID backwards to return the full session handoff chain

### task_plan_api.py

```python
create_plan(agent_id, goal, priority, strategy) -> str
get_plan(plan_id) -> dict | None
update_plan(plan_id, **kwargs) -> bool
add_step(plan_id, plan_status, description, step_order, tool_name, tool_input) -> str
update_step(step_id, **kwargs) -> bool
get_plan_steps(plan_id) -> list
add_dependency(source_plan_id, target_plan_id, dep_type) -> str
get_plan_dependencies(plan_id) -> list
log_tool_call(plan_id, step_id, tool_name, tool_input, tool_output, status, duration_ms) -> str
save_snapshot(plan_id, snapshot_type, context_data) -> str
list_plans(agent_id, status, limit) -> list
delete_plan(plan_id) -> bool
```

- Plan IDs: `'PLAN_' || RAWTOHEX(SYS_GUID())`
- Step IDs: `'STEP_' || RAWTOHEX(SYS_GUID())`
- `add_step` requires `plan_status` parameter — denormalized TASK_PLANS.STATUS for composite FK
- TASK_PLANS PK is `(PLAN_ID, STATUS)` with ROW MOVEMENT enabled
- TASK_STEPS PK is `(STEP_ID, PLAN_ID)`, FK `(PLAN_ID, PLAN_STATUS)` references TASK_PLANS
- Terminal statuses auto-set `COMPLETED_AT = SYSTIMESTAMP`

### harness_api.py

```python
create_harness_template(title, summary, content, category, input_schema, output_schema, execution_mode, importance, owned_by_agent, visibility) -> str
get_harness_template(entity_id) -> dict | None
update_harness_template(entity_id, **kwargs) -> bool
delete_harness_template(entity_id) -> bool
list_harness_templates(category, execution_mode, limit, offset) -> list
get_template_with_variables(entity_id) -> dict | None
instantiate_harness_template(entity_id, variable_values, agent_id) -> str
count_harness_templates(category) -> int
```

- HARNESS_META columns: `TEMPLATE_VERSION`, `INPUT_SCHEMA` (JSON), `OUTPUT_SCHEMA` (JSON), `EXECUTION_MODE`
- `execution_mode`: SEQUENTIAL, PARALLEL, CONDITIONAL
- `instantiate_harness_template`: Creates a TASK_OUTPUT entity with `{variable}` substitution in content, adds USES_HARNESS edge
- `get_template_with_variables`: Extracts variable definitions from INPUT_SCHEMA JSON properties

### security.py

```python
DataMaskingService(context_level).mask_text(text) -> str
DataMaskingService(context_level).mask_dict(data) -> dict
DataMaskingService(context_level).mask_json(json_string) -> str
ReversibleEncryption(key).encrypt(plaintext) -> str
ReversibleEncryption(key).decrypt(ciphertext) -> str
hash_password(password, salt, iterations) -> (hash, salt_hex)
verify_password(password, stored_hash, salt_hex, iterations) -> bool
```

### workspace_api.py

```python
create_workspace(owner_user_id, name, workspace_type, isolation_mode, metadata) -> str
get_workspace(workspace_id) -> dict | None
get_user_workspaces(user_id, status) -> list
update_workspace(workspace_id, **kwargs) -> bool
save_context(workspace_id, agent_id, context_type, context_data, session_id, parent_context_id, visibility) -> str
get_context_chain(workspace_id, limit) -> list
get_latest_context(workspace_id) -> dict | None
create_handoff_session(workspace_id, new_agent_id, handoff_data) -> str
recover_workspace(workspace_id) -> dict
link_task_to_workspace(workspace_id, plan_id) -> bool
get_workspace_tasks(workspace_id) -> list
```

- Workspace IDs: `'WS_' || RAWTOHEX(SYS_GUID())`
- Context IDs: `'CTX_' || RAWTOHEX(SYS_GUID())`
- `workspace_type`: CONVERSATION (default), PROJECT, ANALYSIS
- `isolation_mode`: SHARED (default) or ISOLATED
- `context_type`: SNAPSHOT, CHECKPOINT, HANDOFF, SUMMARY, RECOVERY
- `create_handoff_session`: Creates a new AGENT_SESSION linked to the predecessor, saves a HANDOFF context entry, and updates WORKSPACES to point to the new agent/session
- `recover_workspace`: Returns the complete recoverable state — workspace metadata, context chain (latest 5), active tasks, recent sessions, and scoped entities (ISOLATED mode only)
- `update_workspace` allowed fields: workspace_name, status, isolation_mode, current_agent_id, current_session_id, summary, metadata
- `save_context` auto-serializes dict/list CONTEXT_DATA to JSON
- `save_context` visibility parameter: PRIVATE/SHARED/PUBLIC (default SHARED). Controls cross-agent visibility in collab workspaces: PRIVATE blocks other agents from seeing this context, SHARED allows collab group members to see it, PUBLIC allows all agents to see it. The WS_CTX_AGENT_ACCESS Data Grant enforces this at the database level — agents always see their own context regardless of VISIBILITY.

## PL/SQL API (13 packages: 10 in 2_api.sql + 3 in 6_deep_sec_policy.sql)

### MEMORY_FUSION_ENGINE
- `fuse_similar_memories(category, min_similarity, dry_run)` — Merge similar memories, inserts SIMILAR_TO edges with `RAWTOHEX(SYS_GUID())` IDs, uses `JSON_OBJECT('key' VALUE val)` syntax
- `extract_knowledge_from_memories(category, min_count)` — Auto-extract knowledge, creates ENTITIES + KNOWLEDGE_META with composite FK
- `decay_old_memories(days_threshold, decay_factor)` — Reduce IMPORTANCE (not priority) of old memories
- `get_fusion_stats() RETURN JSON` — Fusion statistics using `JSON_OBJECT` with `VALUE` syntax

### KNOWLEDGE_BASE_API
- `schedule_review(entity_id, entity_type)` — Schedule next spaced review (requires both PK components)
- `record_review(entity_id, entity_type)` — Record review with doubling interval (requires both PK components)
- `get_due_reviews() RETURN SYS_REFCURSOR` — List pending reviews
- `get_concept_lineage(entity_id, entity_type) RETURN JSON` — Ancestor/descendant graph using `JSON_OBJECT`/`JSON_ARRAYAGG` with `VALUE` syntax, joins on composite `(SOURCE_ID, SOURCE_TYPE)`

### AGENT_PERMISSION_MANAGER
- `check_entity_access(agent_id, entity_id) RETURN VARCHAR2` — 'GRANTED'/'DENIED' based on PRIVATE/SHARED/PUBLIC visibility
- `log_access(agent_id, entity_id, access_type, session_id)` — Insert into ENTITY_ACCESS_LOG with `'LOG_' || RAWTOHEX(SYS_GUID())`
- `cleanup_expired_sessions()` — Close sessions inactive >300min (ROW MOVEMENT moves rows to inactive partition)
- `process_collaboration_requests()` — Process collaboration requests

### SESSION_CLEANUP
- `purge_access_logs(days_to_keep)` — Delete old access logs (partition-aware)
- `purge_inactive_sessions(days_to_keep)` — Delete old closed sessions
- `archive_old_entities(days_threshold)` — Archive low-importance memories (IMPORTANCE <= 1)
- `update_tag_counts()` — Reserved for tag count updates

## Deep Sec Connection Functions

- `set_agent_context(agent_id)` — Set agent identity for Deep Sec End User routing. `None` switches to AIADMIN pool.
- `get_current_agent_id()` — Get current agent context from thread-local storage
- `get_end_user_connection(agent_id)` — Get End User connection with Data Grant filtering
- `get_connection()` — Get AIADMIN pool connection (unrestricted by Data Grants)

**v4.0.1 identity boundary**: Business/Portal requests use only the authenticated
Agent's independent database identity. They never call
`set_agent_context(None)` to obtain a Schema Owner connection. Admin routes use
the separately authenticated Admin connection path.

## Admin API (v3.7.0)

Admin API endpoints for Admin/Agent Separation Architecture. Only available in `admin` or `standalone` mode.

### POST /api/admin/agent/register

Register a Business Agent with admin token. Returns encrypted End User credentials.

**Request:**
```json
{
  "admin_token": "<registration-token>",
  "agent_name": "business-agent-1",
  "capabilities": {"type": "research", "skills": ["search", "memory"]}
}
```

**Response:**
```json
{
  "agent_id": "AGENT_XXX",
  "encrypted_credentials": "<base64-encrypted-blob>",
  "schema": "AIADMIN",
  "dsn": "//db-host:1521/service"
}
```

### POST /api/admin/token/generate

Generate a new admin registration token. Requires AIADMIN session.

**Request:** (empty body or `{}`)

**Response:**
```json
{
  "admin_token": "<new-base64-token>",
  "expires_at": "2026-06-14T13:00:00Z"
}
```

### POST /api/admin/token/rotate
### GET /api/admin/skill/list

List available skills. Requires admin_token as query parameter.

| Parameter | Location | Required | Description |
|-----------|----------|----------|-------------|
| admin_token | query | Yes | Admin registration token |
| type | query | No | Filter by skill type |
| runtime | query | No | Filter by runtime |
| keyword | query | No | Search keyword |

Response: `{"skills": [...]}`

### GET /api/admin/skill/{skill_id}/acquire

Acquire skill content. Requires admin_token as query parameter.

| Parameter | Location | Required | Description |
|-----------|----------|----------|-------------|
| skill_id | path | Yes | Skill entity ID |
| admin_token | query | Yes | Admin registration token |
| resource | query | No | Set to 1 to include resource ZIP (base64 encoded) |

Response: Skill metadata + text_content + optional resource_zip (base64)
### POST /api/admin/skill/create

Create a new skill. Requires admin_token in request body.

| Field | Required | Description |
|-------|----------|-------------|
| admin_token | Yes | Admin registration token |
| title | Yes | Skill title |
| skill_name | Yes | Skill name |
| skill_version | No | Version (default 1.0.0) |
| skill_type | No | Type (default CUSTOM) |
| skill_format | No | Format (default TEXT) |
| text_content | No | SKILL.md content |
| skill_description | No | Description |
| runtime | No | Runtime (default PYTHON) |
| visibility | No | PRIVATE/SHARED/PUBLIC |

Response: `{"skill_id": "ENT_xxx", "skill": {...}}`

### POST /api/admin/skill/update

Update an existing skill. Requires admin_token and skill_id in request body.

| Field | Required | Description |
|-------|----------|-------------|
| admin_token | Yes | Admin registration token |
| skill_id | Yes | Skill entity ID |
| title | No | New title |
| skill_name | No | New skill name |
| skill_status | No | ACTIVE/DEPRECATED |
| visibility | No | PRIVATE/SHARED/PUBLIC |

Response: `{"skill_id": "ENT_xxx", "skill": {...}}`

### POST /api/admin/skill/delete

Delete a skill. Requires admin_token and skill_id in request body.

| Field | Required | Description |
|-------|----------|-------------|
| admin_token | Yes | Admin registration token |
| skill_id | Yes | Skill entity ID |

Response: `{"skill_id": "ENT_xxx", "deleted": true}`

### POST /api/admin/skill/upload

Upload resource file for a skill. Requires admin_token, skill_id, filename, and content_base64 in request body.

| Field | Required | Description |
|-------|----------|-------------|
| admin_token | Yes | Admin registration token |
| skill_id | Yes | Skill entity ID |
| filename | Yes | Resource filename |
| content_base64 | Yes | Base64-encoded file content |

Response: `{"skill_id": "ENT_xxx", "upload": {...}}`

Rotate the admin token. Existing Business Agents must re-register with the new token.

**Request:** (empty body or `{}`)

**Response:**
```json
{
  "admin_token": "<rotated-base64-token>",
  "expires_at": "2026-06-14T14:00:00Z",
  "previous_token_invalidated": true
}
```

### Admin Token Functions (Python API)

```python
from scripts.lib.agent_admin_api import generate_admin_token, verify_admin_token
from scripts.lib.agent_admin_api import encrypt_credential_for_distribution, decrypt_credential_from_distribution
from scripts.lib.agent_bootstrap import save_agent_config, load_agent_config

# Generate admin token
token = generate_admin_token()
# Returns: {"token": "<base64>", "expires_at": "..."}

# Verify admin token
is_valid = verify_admin_token("<provided-token>")
# Returns: True/False

# Encrypt credential for distribution
encrypted = encrypt_credential_for_distribution("end_user_password", admin_token)
# Returns: base64-encoded encrypted blob

# Decrypt credential from distribution
password = decrypt_credential_from_distribution(encrypted_blob, admin_token)
# Returns: plaintext credential string

# Save agent config (encrypted)
save_agent_config(config_dict, admin_token, "/path/to/agent_config.json")

# Load agent config (decrypted)
config = load_agent_config(admin_token, "/path/to/agent_config.json")
```

### POST /api/admin/agent/recover

Recover an agent using a one-time recovery code. Resets End User password to prevent dual-active scenarios.

| Field | Required | Description |
|-------|----------|-------------|
| admin_token | Yes | Admin registration token |
| agent_id | Yes | Agent identifier to recover |
| recovery_code | Yes | One-time recovery code (RC-XXXX-XXXX-XXXX) |

Response: `{"agent_id": "...", "recovered": true, "end_user": {"credential_encrypted": "...", "salt": "..."}}`

**Recovery Process:**
1. Verify admin_token + recovery_code
2. Check LAST_SEEN_AT — reject if agent may still be active (< 5 min)
3. Reset End User password — old password invalidated immediately
4. Return new encrypted credentials

**Dual-Active Prevention:** Old process cannot reconnect (password changed). Functionally dead even if still running.

### POST /api/admin/skill/request-access (ENT only)

Request a one-time skill access token. Token must be consumed to get download URL.

| Field | Required | Description |
|-------|----------|-------------|
| admin_token | Yes | Admin registration token |
| agent_id | Yes | Agent requesting access |
| skill_id | Yes | Skill entity ID |
| session_id | No | Session ID for audit |

Response: `{"token_id": "TKN_xxx", "skill_id": "...", "resource_uri": "...", "expires_at": ...}`

### GET /api/admin/skill/dl/{download_token} (ENT only)

Download skill resource using a valid download token. One-time use — token invalidated after download.

| Parameter | Location | Required | Description |
|-----------|----------|----------|-------------|
| download_token | path | Yes | Download token from consume_skill_token |

Response: Resource ZIP file (binary)
