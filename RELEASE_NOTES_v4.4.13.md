# v4.4.13 Release Notes - Development Candidate

Status: implementation and verification in progress. This candidate is not a public release.

## Implemented Changes

- Channel mentions bind explicitly selected members; keyboard completion, IME handling and channel request isolation are improved.
- Compliance template details expose inherited controls and sources. Draft editing uses an expected digest and preserves immutable published versions.
- Model content inspection checks inputs and complete bounded outputs before delivery, including credentials split across stream chunks.
- Portal answers use authorized user/Agent knowledge intersection, fresh citations and database-authoritative model disclosure policy. Service failures no longer generate simulated successful replies.
- Management slash commands use registered parameter schemas and execution rechecks the approved request and contract.
- Portal knowledge extracts work without a configured model profile. Logout releases the Portal connection after revoking its session.

## Database Verification

Clean initialization, real-provider external Agent workflows, native authorization and concurrency checks have been exercised on all six local database editions. Portal policy updates, template inheritance and published immutability have also been verified against the databases. Local baseline services have been upgraded; these results are not a public release approval.

## Pending Release Gates

Full security enforcement, governed management execution, built-in knowledge lifecycle, integrated template workflow and final specification acceptance remain required. Refer to the repository OpenSpec change for authoritative task status. Do not distribute this development candidate as a production release.
