# Chuanxu AI Agent Management Platform v4.3.7

Release date: 2026-08-10

## Deterministic Bootstrap Deployment

v4.3.7 introduces the local Bootstrap Deployment Agent. It can initialize or
upgrade a prepared Oracle AI Database 26ai, PostgreSQL 18, or YashanDB 23.5.4+
target without requiring an external Agent, a Skill runtime, `psql`, or LLM
output as deployment authority. The package executes only its checksum-bound
SQL manifest and records sanitized deployment runs, steps, evidence, and
local-node leases in the database.

The installer performs prepared-target checks before it changes the target.
For Oracle-compatible databases it checks the application service, default and
temporary tablespaces, and deployment-owner privileges. PostgreSQL checks the
server major version, the enabled `vector` and Apache AGE extensions, and the
target schema create privilege. Infrastructure changes remain outside the
default installer and require explicit operator action.

## Model And Embedding Contract Governance

Embedding Profiles now persist provider identity, model ID, optional model
fingerprint, dimension, distance metric, vector normalization, preprocessing,
modalities, execution mode, and encrypted API-key material. A versioned
Embedding Contract freezes the compatible vector-space definition. Embedding
Spaces and platform/template/Agent Bindings select the only Contract a caller
may use.

The supported execution modes are `PLATFORM_MANAGED`, `ENTERPRISE_DIRECT`,
`ENTERPRISE_PROXY`, `PRECOMPUTED_IMPORT`, and `NONE`. Platform-managed
generation is verified against both the configured Contract and the deployed
physical vector dimension. Direct, proxy, and precomputed modes retain the
same database Contract without moving an enterprise secret into the platform.

New vector writes and vector retrieval are isolated by Embedding Space and
Contract. They cannot silently mix different model dimensions, normalization
rules, preprocessing, or provider identities. Existing vectors are retained
as the non-writable `LEGACY_DEFAULT` space until an authorized re-embedding
cutover is completed.

## Native And External Agent Continuity

During deployment, the Bootstrap Deployment Agent creates the existing
platform-native management identities and, when an approved LLM Profile is
configured, attaches it only to the Platform Admin Agent and the Enterprise
Compliance Admin Agent. Business Agent activation remains human-governed. If
a default Embedding Binding exists, a Business Agent cannot activate until its
Contract is ready; management Agents are not blocked by an optional vector
configuration.

External Skill-first registration remains supported. External Agents are
subject to the same Contract at vector-write and vector-retrieval boundaries,
without receiving schema-owner credentials or a platform secret.

## Operations And Packaging

Use the package-local command below after preparing `config.json`:

```bash
bash scripts/install_platform.sh initialize \
  --database <oracle|pg|yashandb> \
  --edition <community|enterprise> \
  --config config.json
```

`status`, `verify`, `resume`, and `upgrade` use the same checked manifest.
Sensitive database, LLM, routing, security, and Embedding API-key fields are
encrypted with AES-256-GCM after a successful deployment. The release includes
the additive `33_v4_3_7_bootstrap_embedding.sql` migration for every adapter.
Enterprise editions retain the separate Compliance Admin Agent and compliance
boundary; Community editions do not expose Enterprise compliance behavior.

Dashboard mutations only create audited Embedding bindings and bounded jobs.
Bulk ingestion and re-embedding run outside the HTTP request path through the
lease-protected local worker:

```bash
"$PYTHON_BIN" scripts/embedding_worker.py --limit 10
```

The Worker accepts only `PLATFORM_MANAGED` or `ENTERPRISE_PROXY` Profiles whose
target Space is verified and writable. `ENTERPRISE_DIRECT` remains Agent-side
and `PRECOMPUTED_IMPORT` remains an explicitly supplied-vector path.
