# v4.4.13 Release Notes

Status: implementation and verification in progress. This candidate is not a public release.

## Implemented Changes

- Channel mentions bind explicitly selected members; keyboard completion, IME handling and channel request isolation are improved.
- Compliance template details expose inherited controls and sources. Draft editing uses an expected digest and preserves immutable published versions.
- Model content inspection checks inputs and complete bounded outputs before delivery, including credentials split across stream chunks.
- Portal answers use authorized user/Agent knowledge intersection, fresh citations and database-authoritative model disclosure policy. Service failures no longer generate simulated successful replies.
- Management slash commands use registered parameter schemas and execution rechecks the approved request and contract.
- Portal knowledge extracts work without a configured model profile. Logout releases the Portal connection after revoking its session.
- Migrations 80-81 initialize and idempotently complete six ACTIVE/PUBLIC bilingual product-knowledge topics on Oracle, PostgreSQL, and YashanDB. English and Chinese queries can retrieve the same governed platform facts.
- Portal Agent assignment now requires an ACTIVE Agent Principal, usable registration/database identity, and effective `knowledge.read`; legacy pool aliases are not silently promoted.
- Removing a Portal conversation marks its Workspace `ABANDONED`, preserves referenced evidence, and removes the visible row immediately. Portal Exit uses the Dashboard confirmation Drawer pattern.
- Template cloning and validation bind source digests and enforce inheritance before writes. Mutations reject unknown schema fields, invalid enums, null controls and duplicate aliases. Structured editing and JSON share a draft with control-change preview.
- Management commands add scoped Agent diagnosis, finding summaries, management approval summaries and capability discovery. Community editions reject Enterprise compliance commands before querying compliance data.
- Management Action Cards bind content inspection to immutable rules and recheck it before execution. Older cards without this binding must be proposed again.
- Portal knowledge policy administration includes knowledge-first/knowledge-only modes, optional model supplementation, model disclosure permissions and optimistic version checks.
- Registered tools can be inspected, edited as active/deprecated, and softly retired from the available catalog through CSRF-protected tools.write operations.
- Skill management uses the same row-level action pattern as the Tool catalog, including view, edit, download, and delete controls with a compact mobile layout. Deterministic local test Skill fixtures are provided for read-only SQL, incident triage, and Portal grounding.
- High-impact Agent containment creates an immutable Action Card and requires confirmation by a separate authorized Human before a containment command is issued.
- Release evidence now includes a frozen bilingual 240-sample content-security holdout, real-provider streaming/usage measurements, and cross-process lease/fencing recovery.

## Database Verification

Clean initialization, real-provider external Agent workflows, native authorization and concurrency checks have been exercised on all six local database editions. Portal policy updates, template inheritance and published immutability have also been verified against the databases. Local baseline services have been upgraded; these results are not a public release approval.
