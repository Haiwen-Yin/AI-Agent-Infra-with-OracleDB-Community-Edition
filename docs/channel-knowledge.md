# v4.4.16 Channel and Portal knowledge answers

Portal assigns an approved idle local Agent to a signed-in user; external Agent
enrollment is a separate workflow. Ordinary Channels dispatch explicit mentions
subject to current human, Agent, Security Domain and private-thread membership.

Both entry points use `knowledge_grounding.search`: current `knowledge.read`
authority is required for both Principals, and SQL intersects their source
visibility with active status and expiry. This component currently uses keyword
retrieval, so vector-index synchronization is not a prerequisite for matching.

Portal additionally applies knowledge-only/knowledge-first policy, explicit
model supplementation and a model-profile disclosure allowlist. A profile
without disclosure approval receives no source text; authorized extracts remain
available. Before returning an answer, Portal rechecks source digests, readers
and policy version.

Channels intersect retrieved sources with current Channel/private-thread readers.
They apply the same disclosure allowlist and knowledge mode: unapproved profiles
receive no source text, while authorized extracts remain available. Without shared
sources, general-model answers require policy approval and explicit labeling.
Before model dispatch and response publication, source digests, current readers,
model binding and policy version are rechecked. Historical answers and execution
results recheck each reader's source access, including newly admitted members.
Legacy requests lacking policy bindings require a new request, not automatic retry.
Source regression is not six-edition live or citation-presentation acceptance.

Diagnose source contents and expiry, both Principals' effective permissions,
source policy, actual retrieval/input and runtime evidence separately. Replacing
a version string does not refresh product facts. Preserve the Agent template's
required isolation when repairing a deployment.

When knowledge-first policy permits a general-model answer after no match,
Portal and Channels show a separate notice: “No knowledge-base match. This answer
uses general model knowledge and is not a conclusion from the knowledge base.”
The notice supports both interface languages and Portal streaming completion,
ordinary replies and history. Channel history uses authorized persisted execution
metadata; unverifiable or failed executions are not labeled as successful model
answers. Retrieval or model failures remain errors, not successful supplementation.
English conversational filler is excluded from keyword matching; this does not
establish semantic relevance for every question.
Chinese subjects remain complete after common question wrappers are removed;
two-character fragments are not independent matches. For example, “甲骨文公司”
does not match an unrelated source merely containing “公司”. This conservative
keyword retrieval does not provide synonym expansion or general semantic search.
All retained terms must match the same source, not just a generic term from a
multi-keyword or mixed-language question. Authorized source titles/content are
rechecked before use: English terms require word boundaries and underscores are
literal. A summary-only candidate is insufficient. Long words are not split;
more than 24 distinct retained terms returns NO_MATCH without dropping terms.
These conservative rules may omit paraphrases or multi-source answers. Keyword
coverage does not certify factual relevance or current model knowledge.

For an idle local Portal Agent missing its unified Principal, an administrator
with `platform.manage` and `users.roles.manage.all` may run
`scripts/repair_portal_pool.py --actor <admin-principal-id> --agent <agent-id>
--reason <reason>` using the installation Python and private `CX_CONFIG_PATH`.
Repeat `--agent` for exact targets. Only unassigned local Portal-managed POOL
records with ACTIVE registrations qualify. The transactional, audited repair
creates missing identities only; it does not release another user's Agent,
reactivate disabled identities or add Knowledge permissions.

Use `scripts/tools/repair_knowledge.py` for an authenticated administrative repair.
The reviewed JSON array binds each exact `entity_id` and `expected_digest` to its
replacement `title`, `summary` and `content`. Content and audit commit together;
existing source policies, unrelated entities and custom role permissions remain
unchanged. Optional `--grant-agent-read` adds only `knowledge.read`, preserving
explicit denials and historical migration checksums. Supply `--plan`,
`--password-file` and `--reason`; an empty array allows a role-only repair.

Human self-registration and external Agent enrollment are separate controls.
On the OCI deployment, human accounts are requested from the developer; external
Agent enrollment remains open under its governed activation/credential flow.
This is a deployment setting, not a default for all installations.
