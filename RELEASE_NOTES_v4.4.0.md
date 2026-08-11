# AI Agent Infra v4.4.0 Release Notes

## Governed Software Delivery Graph

v4.4.0 makes Spec Driven Development a native Chuanxu capability. Structured
requirements, scenarios, acceptance criteria, decisions, tasks, reviews,
evidence, resources and release baselines are stored in the database and are
available to authorized collaborating Agents.

## OpenSpec Boundary

OpenSpec can generate or import proposal, design, task and specification
material. Chuanxu keeps an immutable source snapshot, normalizes the material
into typed database objects and blocks an execution baseline on unresolved
requirement, acceptance, security, interface, data or migration fragments.
After an execution baseline is approved, OpenSpec CLI and local Markdown are
optional and do not control execution, code changes, tests, reviews or release.

## Governed Execution

Approved tasks compile into a bounded execution graph. Nodes declare roles,
read/write sets, budgets, guards, dependencies and evidence requirements.
Dynamic graph changes are drafts subject to deterministic compilation,
checkpoints and risk-driven local or whole-run pause. Permission, security,
public-contract, data-model, embedding-contract and irreversible-effect
changes require a whole-run pause and configured human approval.

## Software Delivery

The Software Delivery Profile provides controlled Requirements, Architect,
Planner, Coding, Database Migration, Testing, Security Review, Code Review and
Release roles. Concurrent tasks use bounded resource leases and isolated
worktrees, branches, containers or customer-equivalent environments. The
first SCM adapters are local Git and GitHub; credentials are references to a
controlled provider and are never stored in task text or the Web process.

## Evidence And Editions

Agent completion claims are not independent evidence. Worker or customer CI
results record the command or reference, environment summary, commit or
artifact digest and verification time. Digest changes make dependent evidence
stale. Community and Enterprise share the SDD core; Enterprise adds
organization policy, separation of duties, multi-party approval and extended
SCM/compliance governance.

## Compatibility

The migration from v4.3.7 is additive and preserves existing SPEC, Task, Loop,
Graph, Channel, Artifact, approval and audit facts. The package is validated
for Oracle AI Database 26ai, PostgreSQL 18 with Apache AGE, and YashanDB
23.5.4 in Community and Enterprise editions.

