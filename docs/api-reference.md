# API Reference - Oracle Memory System v2.0.0

## Python API (scripts/lib/)

### memory_api.py
```python
create_memory(name, content, category, memory_type, priority, tags, metadata, owned_by_agent, visibility, accessible_to) -> int
get_memory(entity_id) -> dict | None
update_memory(entity_id, **kwargs) -> bool
delete_memory(entity_id) -> bool
search_memories(keyword, category, visibility, owned_by_agent, limit, offset) -> list
get_agent_memories(agent_id, limit) -> list
count_memories(category) -> int
```

### knowledge_api.py
```python
create_concept(name, concept_type, description, category, content, source_type, source_entity_ids, confidence, tags, metadata, owned_by_agent, visibility) -> int
get_concept(entity_id) -> dict | None
update_concept(entity_id, **kwargs) -> bool
delete_concept(entity_id) -> bool
create_relationship(source_id, target_id, edge_type, strength, confidence, properties) -> int
get_relationships(entity_id, direction) -> list
delete_relationship(edge_id) -> bool
search_concepts(keyword, concept_type, category, validation_status, limit) -> list
get_statistics() -> dict
get_concept_neighbors(entity_id, max_depth) -> list
```

### agent_api.py
```python
register_agent(agent_id, agent_name, agent_type, capabilities, description, permission_level) -> bool
get_agent(agent_id) -> dict | None
list_agents(agent_type, status) -> list
disable_agent(agent_id, reason) -> bool
enable_agent(agent_id) -> bool
create_session(agent_id, working_memory_id) -> str | None
update_session_context(session_id, context) -> bool
close_session(session_id) -> bool
get_active_sessions(agent_id) -> list
log_access(agent_id, entity_id, access_type) -> None
get_access_history(agent_id, limit) -> list
request_collaboration(sharing_agent, receiving_agent, entity_id, reason) -> int | None
approve_collaboration(collab_id) -> bool
reject_collaboration(collab_id) -> bool
get_pending_requests(agent_id, role) -> list
```

### task_plan_api.py
```python
create_task_plan(plan_name, plan_type, description, goal, priority, steps, metadata, tags) -> int
get_task_plan(plan_id) -> dict | None
get_task_steps(plan_id) -> list
update_step_status(plan_id, step_id, status, result, error_msg) -> bool
save_snapshot(plan_id, context, snapshot_type) -> int
resume_task(plan_id) -> dict | None
log_tool_call(plan_id, tool_name, action, step_id, status, result_size, duration_ms) -> int
add_dependency(source_plan_id, target_plan_id, dependency_type, condition) -> int
search_completed_tasks(plan_type, status, limit) -> list
```

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

## PL/SQL API (packages)

### MEMORY_FUSION_ENGINE
- `fuse_similar_memories(category, min_similarity, dry_run)` - Merge similar memories
- `extract_knowledge_from_memories(category, min_count)` - Auto-extract knowledge
- `decay_old_memories(days_threshold, decay_factor)` - Reduce priority of old memories
- `get_fusion_stats() RETURN JSON` - Fusion statistics

### KNOWLEDGE_BASE_API
- `validate_concept(entity_id, validator)` - Mark concept as validated
- `deprecate_concept(entity_id, reason)` - Deprecate with reason
- `create_concept_version(entity_id, new_content)` - Version a concept
- `get_unvalidated() RETURN SYS_REFCURSOR` - List pending concepts
- `get_concept_lineage(entity_id) RETURN JSON` - Ancestor/descendant graph

### AGENT_PERMISSION_MANAGER
- `check_entity_access(agent_id, entity_id, access_type) RETURN VARCHAR2` - 'GRANTED'/'DENIED'
- `grant_access(agent_id, entity_id, granted_by)` - Add to ACCESSIBLE_TO
- `revoke_access(agent_id, entity_id)` - Remove from ACCESSIBLE_TO
- `cleanup_expired_sessions()` - Close sessions inactive >300min
- `process_collaboration_requests()` - Expire requests >7 days

### SESSION_CLEANUP
- `purge_access_logs(days_to_keep)` - Delete old access logs
- `purge_inactive_sessions(days_to_keep)` - Delete old closed sessions
- `archive_old_entities(days_threshold)` - Archive low-priority memories
- `update_tag_counts()` - Recalculate tag usage counts
