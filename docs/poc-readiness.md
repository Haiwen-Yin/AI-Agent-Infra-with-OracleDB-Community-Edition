# POC Readiness and Evidence v4.1.0

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

This guide defines the repeatable technical evidence boundary for a four-week
POC. It is not a promise that a customer has accepted the product or that a
specific efficiency improvement will occur.

## Scope

The mandatory technical acceptance items are:

1. Deploy the agreed edition in the customer environment.
2. Register the agreed Agent identities and verify their inventory.
3. Show Agent status and activity through authenticated operations.
4. Produce one scoped, bounded audit trace.
5. Demonstrate one Agent disable or access-revocation operation.

Token consumption and efficiency are observations. They must record the
dataset, workload, database, scale, concurrency, and measurement boundary,
and are not fixed acceptance targets.

## Readiness Check

Run the check with the Linuxbrew Python 3.14 interpreter. It is read-only and
does not deploy schema objects:

```bash
python3.14 scripts/poc_readiness.py \
  --oracle-config /path/to/oracle-config.json \
  --pg-config /path/to/pg-config.json \
  --yashandb-config /path/to/yashandb-config.json \
  --edition enterprise \
  --output poc-readiness.json
```

The report records configuration field presence, owner-only permission state,
driver availability, connectivity, database version, required object counts,
the `SKILL_META` contract, and remediation steps. It never records credential
values, DSNs, or raw driver errors. PostgreSQL may use peer, trust, or a
restricted `.pgpass`/driver authentication path instead of a password in the
config file. A missing capability prevents a POC-ready result.

## Acceptance Evidence

The release evidence reports can be assembled into a POC report:

```bash
python3.14 scripts/poc_evidence.py \
  --manifest release_evidence/manifest.json \
  --clean release_evidence/clean-deployments.json \
  --modes release_evidence/mode-matrix.json \
  --governance release_evidence/governance-live.json \
  --readiness poc-readiness.json \
  --skill SKILL.md \
  --output poc-evidence.json
```

The report links each mandatory item to a timestamped report and SHA-256
hash. Native OpenClaw and Hermes executables are only claimed as validated
when their version and executed operations are present. A framework-neutral
`SKILL.md` contract check may be recorded separately.

## Support Bundle

Only sanitized summaries and bounded logs belong in a support bundle:

```bash
python3.14 scripts/support_bundle.py \
  --manifest poc-evidence.json \
  --poc poc-evidence.json \
  --readiness poc-readiness.json \
  --config /path/to/oracle-config.json \
  --output support-bundle.zip \
  --manifest-output support-bundle.json
```

Original configuration files are excluded. Log input is capped at 1 MiB per
file and common password, token, API-key, and secret fields are redacted.

## Exclusions and Rollback

The standard POC does not include public exposure, shared-database multi-
tenancy, automatic discovery of unregistered Agents, model quality claims,
exactly-once external side effects, or unrestricted custom development.

Before migration, back up the database/schema, encrypted configuration,
master-key file, and exact release archive. Rollback stops v4.1.0 services and
restores the coordinated v4.0.1 snapshot. External side effects and completed
credential rotations require separate operational handling.

## Support Boundary

The POC scope, response expectations, escalation contacts, and any exception
to the standard acceptance must be written into the customer agreement. A
technical evidence report does not create an SLA or imply unlimited support.
