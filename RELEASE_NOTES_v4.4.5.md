# AI Agent Infra with DB v4.4.5

## Highlights

v4.4.5 preserves Dashboard child-view state through bounded URL deep links.
Only whitelisted views and authorized bounded resource identifiers are stored;
credentials, tokens, message bodies, and model secrets are excluded.

The Graph Runtime now records the immutable Definition digest, compiled Plan
digest, compatibility level, State schema version, and budget schema version
used for each newly admitted Run. Run admission fails closed if the Plan is
from another Graph Version or its digest does not match.

Agent Cards and protocol capability metadata are descriptive only. Skills are
projected from the intersection of Agent-advertised metadata and explicit
platform grants. A fork that can replay a `NON_IDEMPOTENT` external effect is
created paused before any Worker claim and requires an approved
`GRAPH_FORK_REPLAY` request bound to the child Run or bounded compensation
evidence before resume.

The release adds equivalent additive migration `45_v4_4_5_graph_run_contract.sql`
for Oracle, PostgreSQL, and YashanDB. Database cluster HA, external-system
exactly-once behavior, and customer-specific failover remain deployment
responsibilities and are not claimed by this release.
