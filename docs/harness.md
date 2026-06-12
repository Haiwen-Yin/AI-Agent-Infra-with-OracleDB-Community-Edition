# Harness Template System - AI Agent Infra v3.5.0 (2026-06-11) - Community Edition

## Overview

A Harness Template is a reusable agent execution blueprint stored as an `ENTITY` with `ENTITY_TYPE='HARNESS_TEMPLATE'`. It defines input/output schemas, execution mode, and runtime configuration for an agent. Templates are extended via HARNESS_META and support instantiation with variable substitution.

## Architecture

```
ENTITIES (ENTITY_TYPE='HARNESS_TEMPLATE')
  PK: (ENTITY_ID, ENTITY_TYPE)

HARNESS_META (Reference Partitioned)
  PK: (ENTITY_ID, ENTITY_TYPE)
  Columns: TEMPLATE_VERSION, INPUT_SCHEMA (JSON), OUTPUT_SCHEMA (JSON), EXECUTION_MODE

ENTITY_TAGS (via ENTITIES)
  Tags attached to template entities

ENTITY_EDGES (EDGE_TYPE='USES_HARNESS')
  Instance → Template (created on instantiation)
```

| Storage | Purpose |
|---------|---------|
| `ENTITIES` columns | TITLE, CONTENT (template body with {variable} slots), SUMMARY, CATEGORY, STATUS, IMPORTANCE, VISIBILITY, SOURCE_AGENT, RETRIEVAL_COUNT |
| `HARNESS_META` | Lifecycle metadata: version, input/output schemas, execution mode |
| `ENTITY_TAGS` | Normalized tags via TAGS table |

## HARNESS_META Schema (v2.1)

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| ENTITY_ID | VARCHAR2(64) | — | FK to ENTITIES |
| ENTITY_TYPE | VARCHAR2(32) | 'HARNESS_TEMPLATE' | Denormalized for composite FK |
| TEMPLATE_VERSION | VARCHAR2(32) | — | Template version number |
| INPUT_SCHEMA | JSON | NULL | JSON Schema defining input variables |
| OUTPUT_SCHEMA | JSON | NULL | JSON Schema defining expected output |
| EXECUTION_MODE | VARCHAR2(32) | 'SEQUENTIAL' | SEQUENTIAL, PARALLEL, or CONDITIONAL |

**v2.1 changes from v2.0**:

| v2.0 Column | v2.1 Replacement |
|-------------|-----------------|
| VARIABLES (JSON) | INPUT_SCHEMA (JSON Schema format) |
| TEMPLATE_STATUS | Use ENTITIES.STATUS |
| CHANGELOG (JSON) | *(removed)* |

## Input/Output Schema

INPUT_SCHEMA and OUTPUT_SCHEMA use JSON Schema format to define variables:

```json
{
  "type": "object",
  "properties": {
    "role": { "type": "string", "description": "Agent role", "default": "Analyst" },
    "domain": { "type": "string", "description": "Knowledge domain" },
    "objective": { "type": "string", "description": "Task objective" },
    "query": { "type": "string", "description": "Search query" }
  },
  "required": ["role", "query"]
}
```

The `get_template_with_variables()` function parses INPUT_SCHEMA to extract variable definitions with name, type, description, default value, and required flag.

## Execution Modes

| Mode | Description |
|------|-------------|
| SEQUENTIAL | Steps execute in order, one at a time |
| PARALLEL | Steps execute concurrently where possible |
| CONDITIONAL | Step execution based on conditions and branching |

## API Reference

### CRUD

| Function | Description |
|----------|-------------|
| `create_harness_template(title, summary, content, category, input_schema, output_schema, execution_mode, importance, owned_by_agent, visibility)` | Create a new template. Returns `entity_id` (str). Creates ENTITIES row + HARNESS_META row |
| `get_harness_template(entity_id)` | Retrieve template with joined `HARNESS_META`. Returns dict or `None` |
| `update_harness_template(entity_id, **kwargs)` | Update entity fields and/or meta fields (input_schema, output_schema, execution_mode, template_version) |
| `delete_harness_template(entity_id)` | Delete template's HARNESS_META row and ENTITIES row. Returns `bool` |
| `list_harness_templates(category, execution_mode, limit, offset)` | List templates with optional category and execution_mode filters |
| `count_harness_templates(category)` | Count templates, optionally filtered by category |

### Variable Extraction & Instantiation

| Function | Description |
|----------|-------------|
| `get_template_with_variables(entity_id)` | Parse INPUT_SCHEMA JSON to extract variable definitions. Returns dict with `variables` list |
| `instantiate_harness_template(entity_id, variable_values, agent_id)` | Create a TASK_OUTPUT entity with `{variable}` substitution in content, add USES_HARNESS edge. Returns instance `entity_id` (str) |

### Instantiation Details

`instantiate_harness_template` performs the following:

1. Retrieves the template via `get_harness_template`
2. Substitutes `{variable}` slots in CONTENT using `variable_values` dict
3. Creates a new ENTITY with `ENTITY_TYPE='TASK_OUTPUT'`
4. Creates an `ENTITY_EDGES` row with `EDGE_TYPE='USES_HARNESS'`, `SOURCE_TYPE='TASK_OUTPUT'`
5. Returns the new instance entity_id

```python
from scripts.lib.harness_api import instantiate_harness_template

instance_id = instantiate_harness_template(
    entity_id="HARNESS_ABC123...",
    variable_values={"role": "Financial Analyst", "query": "Q3 earnings"},
    agent_id="agent-1",
)
# instance_id → new TASK_OUTPUT entity with substituted content
```

## Workflow Examples

### Creating a Template

```python
from scripts.lib.harness_api import create_harness_template, add_memory_tags

tid = create_harness_template(
    title="Sentiment Analyzer",
    summary="Analyzes text sentiment with memory-backed context",
    content="You are a {role}. Analyze sentiment of: {text}",
    category="analytics",
    input_schema={
        "type": "object",
        "properties": {
            "role": {"type": "string", "default": "Sentiment Analyzer"},
            "text": {"type": "string"},
        },
        "required": ["text"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "sentiment": {"type": "string"},
            "confidence": {"type": "number"},
        },
    },
    execution_mode="SEQUENTIAL",
    importance=7,
    visibility="SHARED",
)

add_memory_tags(tid, ["nlp", "sentiment", "analytics"])
```

### Instantiating a Template

```python
from scripts.lib.harness_api import instantiate_harness_template

instance_id = instantiate_harness_template(
    entity_id=tid,
    variable_values={"role": "Financial Analyst", "text": "Markets rallied today"},
    agent_id="agent-1",
)
# Content becomes: "You are a Financial Analyst. Analyze sentiment of: Markets rallied today"
```

### Template Lifecycle

```
ACTIVE ──update_harness_template(status='ARCHIVED')──▸ ARCHIVED
  │
  └── instantiate to create TASK_OUTPUT entities
```

## Built-in Templates

Seeded by `scripts/deploy/4_harness_templates.sql`. All use MERGE for idempotent re-runs.

| Template | Category | Execution Mode | Input Variables | Output Fields |
|----------|----------|---------------|-----------------|---------------|
| **Research Analyst** | research | SEQUENTIAL | role, domain, objective, query | findings, sources |
| **Code Assistant** | development | SEQUENTIAL | role, language, guidelines, task | solution, explanation |
| **Data Analyst** | analytics | PARALLEL | role, focus_area, data_query | analysis, recommendations |
| **Task Planner** | orchestration | CONDITIONAL | role, constraints, objective | plan, dependencies |
| **Security Auditor** | security | SEQUENTIAL | role, policies, action | assessment, risks, mitigations |

All templates are seeded with IMPORTANCE=2, VISIBILITY='SHARED', OWNED_BY_AGENT='SYSTEM'.
