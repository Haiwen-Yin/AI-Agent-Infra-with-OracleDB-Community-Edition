# Harness Template System - Oracle Memory System v2.0.0

## Overview

A Harness Template is a reusable agent execution blueprint stored as an `ENTITY` with `ENTITY_TYPE='HARNESS_TEMPLATE'`. It defines the complete runtime configuration for an agent: prompt templates, tool bindings, memory access, guardrails, and evaluation criteria. Templates support inheritance, variable substitution, and lifecycle management.

## Architecture

```
ENTITIES (ENTITY_TYPE='HARNESS_TEMPLATE')
  └── METADATA JSON column → prompt_templates, tool_bindings, memory_access,
                               guardrails, evaluation, variables

HARNESS_META
  └── TEMPLATE_VERSION, TEMPLATE_STATUS, VARIABLES, CHANGELOG

ENTITY_EDGES (EDGE_TYPE='DERIVES_FROM')
  └── Child template → Parent template (inheritance chain)
```

| Storage | Purpose |
|---------|---------|
| `ENTITIES.METADATA` | Core harness properties (JSON) |
| `HARNESS_META` | Lifecycle metadata: version, status, variables, changelog |
| `ENTITY_EDGES` | Inheritance via `DERIVES_FROM` edges |

## Template Structure

The `ENTITIES.METADATA` JSON column stores all harness properties:

```json
{
  "prompt_templates": {
    "system": "You are a {role} specializing in {domain}.",
    "user": "{query}",
    "response": "## Findings\n{findings}"
  },
  "tool_bindings": [
    {"name": "memory_search", "access": "read"},
    {"name": "memory_create", "access": "write"}
  ],
  "memory_access": {
    "short_term": true,
    "long_term": true,
    "compaction": true,
    "access_policy": "read_write"
  },
  "guardrails": {
    "max_iterations": 15,
    "max_execution_time": 300,
    "context_window_strategy": "summarize",
    "content_moderation": true,
    "pii_filtering": true,
    "max_retry_limit": 3
  },
  "evaluation": {
    "output_format": "structured",
    "quality_threshold": 0.8
  },
  "variables": {
    "role": "Research Analyst",
    "domain": "general"
  }
}
```

- **prompt_templates**: Slot names mapped to parameterized strings. `{var}` slots are substituted at instantiation. The `system` key is required for validation.
- **tool_bindings**: List of `{name, access}` dicts. Merged from explicit bindings + `tool_sets`.
- **memory_access**: Controls which memory tiers the agent can access.
- **guardrails**: Runtime safety limits. Can be set from presets or custom values.
- **evaluation**: Output format and quality threshold for validation.
- **variables**: Default values for prompt template slots.

## Built-in Tool Sets

| Tool Set | Tools |
|----------|-------|
| `memory_tools` | `memory_search` (read), `memory_create` (write), `memory_update` (write), `memory_delete` (write) |
| `knowledge_tools` | `knowledge_search` (read), `knowledge_create` (write), `knowledge_update` (write), `knowledge_graph_query` (read) |
| `agent_tools` | `agent_register` (write), `session_create` (write), `collaboration_request` (write) |
| `security_tools` | `data_mask` (read), `data_unmask` (read) |
| `task_tools` | `task_plan_create` (write), `task_step_execute` (write), `task_status_query` (read) |

Pass tool set names via `tool_sets` parameter in `create_template`. Bindings are merged with any explicit `tool_bindings`.

## Guardrail Presets

| Preset | max_iterations | max_execution_time | context_window | content_moderation | pii_filtering | max_retry_limit |
|--------|---------------|--------------------|---------------|-------------------|--------------|----------------|
| `conservative` | 5 | 60s | sliding | true | true | 1 |
| `balanced` | 15 | 300s | summarize | true | true | 3 |
| `aggressive` | 50 | 900s | truncate | false | false | 5 |

Default: `balanced`. Specify via `guardrail_preset` parameter or provide custom `guardrails` dict.

## API Reference

### CRUD

| Function | Description |
|----------|-------------|
| `create_template(name, ...)` | Create a new template. Returns `entity_id`. Params: `prompt_templates`, `tool_bindings`, `tool_sets`, `memory_access`, `guardrails`, `guardrail_preset`, `evaluation`, `variables`, `category`, `tags`, `metadata`, `owned_by_agent`, `visibility`, `parent_template_id` |
| `get_template(entity_id)` | Retrieve template with joined `HARNESS_META`. Returns dict or `None` |
| `list_templates(category, status, limit)` | List templates with optional filters. Default limit 100 |
| `update_template(entity_id, **kwargs)` | Update entity fields (`name`, `description`, `category`, `tags`, `metadata`, `visibility`) and/or meta fields (`template_status`, `changelog`) |
| `delete_template(entity_id)` | Delete template, its `HARNESS_META` row, and all related edges. Returns `bool` |

### Resolution & Instantiation

| Function | Description |
|----------|-------------|
| `resolve_template(entity_id)` | Recursively resolve inheritance chain. Merges parent properties into child via deep merge. Child keys override parent |
| `instantiate_template(template_id, variables, overrides, agent_id)` | Resolve template, substitute `{variables}` in prompts, apply overrides. Returns runtime-ready dict with `instance_meta` |

### Inheritance & Validation

| Function | Description |
|----------|-------------|
| `derive_template(parent_id, name, ...)` | Create child template from parent with optional `overrides`. Deep-merges parent props, creates `DERIVES_FROM` edge. Returns `entity_id` |
| `validate_template(entity_id)` | Check template integrity. Validates: `system` prompt exists, variables are declared, no duplicate tool bindings, `max_iterations > 0`, memory access enabled. Returns `{valid, errors, warnings}` |
| `get_template_lineage(entity_id)` | List all `DERIVES_FROM` edges from this template to its parents |

### Lifecycle

| Function | Description |
|----------|-------------|
| `publish_template(entity_id)` | Set `TEMPLATE_STATUS='PUBLISHED'`. Returns `bool` |
| `deprecate_template(entity_id, reason)` | Set `TEMPLATE_STATUS='DEPRECATED'`, append changelog entry. Returns `bool` |

## Workflow Examples

### Creating a Template from Scratch

```python
from scripts.lib.harness_api import create_template, publish_template

tid = create_template(
    name="Sentiment Analyzer",
    description="Analyzes text sentiment with memory-backed context",
    prompt_templates={
        "system": "You are a {role}. Analyze sentiment of the input.",
        "user": "{text}",
        "response": "Sentiment: {sentiment}\nConfidence: {confidence}"
    },
    tool_sets=["memory_tools", "knowledge_tools"],
    guardrail_preset="balanced",
    variables={"role": "Sentiment Analyzer", "text": "", "sentiment": "", "confidence": ""},
    category="analytics",
    visibility="SHARED",
)

publish_template(tid)
```

### Instantiating a Template with Variables

```python
from scripts.lib.harness_api import instantiate_template

instance = instantiate_template(
    template_id=tid,
    variables={"role": "Financial Sentiment Analyst", "text": "Markets rallied today"},
)

# instance["prompt_templates"]["system"] → "You are a Financial Sentiment Analyst. Analyze sentiment of the input."
# instance["prompt_templates"]["user"] → "Markets rallied today"
```

### Deriving a Child Template with Overrides

```python
from scripts.lib.harness_api import derive_template

child_id = derive_template(
    parent_id=tid,
    name="Strict Sentiment Analyzer",
    overrides={
        "guardrails": {"max_iterations": 5, "max_retry_limit": 1},
        "evaluation": {"quality_threshold": 0.95},
    },
)
# Child inherits all parent props; guardrails and evaluation are overridden
```

### Template Lifecycle

```
DRAFT ──publish_template()──▸ PUBLISHED ──deprecate_template()──▸ DEPRECATED
  │                                                          │
  └── edit/update while in DRAFT                              └── can still be read/derived
```

```python
from scripts.lib.harness_api import create_template, publish_template, deprecate_template

tid = create_template(name="Experimental Agent", prompt_templates={"system": "{role}"}, variables={"role": "test"})

publish_template(tid)          # DRAFT → PUBLISHED
deprecate_template(tid, reason="Replaced by v2")  # PUBLISHED → DEPRECATED
```

## Built-in Templates

Seeded by `scripts/deploy/4_harness_templates.sql`. All start as `PUBLISHED`.

| Template | Category | Tool Sets | Guardrail Preset | Use Case |
|----------|----------|-----------|-----------------|----------|
| **Research Analyst** | research | knowledge_tools, memory_tools | balanced | Research and analysis with memory-backed retrieval |
| **Code Assistant** | development | knowledge_tools, task_tools | balanced | Code generation and development tasks |
| **Data Analyst** | analytics | knowledge_tools, memory_tools | conservative | Data analysis and reporting |
| **Task Planner** | orchestration | task_tools, agent_tools | balanced | Task decomposition and multi-step planning |
| **Security Auditor** | security | security_tools, knowledge_tools | conservative | Security review and compliance auditing |
