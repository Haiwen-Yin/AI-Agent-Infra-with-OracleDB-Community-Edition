# Harness Template System - AI Agent Infra with DB v4.1.0

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## Overview

A Harness Template is a reusable agent execution blueprint stored as an `ENTITY` with `ENTITY_TYPE='HARNESS_TEMPLATE'`. It defines input/output schemas, execution mode, and runtime configuration for an agent. Templates are extended via HARNESS_META and support instantiation with variable substitution.

## Architecture

```
ACTIVE ──update(status='ARCHIVED')──▸ ARCHIVED
ACTIVE ──deploy()──▸ DEPLOYED
DRAFT ──publish()──▸ ACTIVE
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
