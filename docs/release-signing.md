# Release archive signing v4.4.16

The upgrade service verifies an Ed25519 signature using the operator-provided
`CX_RELEASE_SIGNING_PUBLIC_KEY` (URL-safe Base64 of the 32-byte public key).
An uploaded `VERIFIED` label never establishes trust. Use the archive upload
workflow; the metadata-only staging endpoint rejects requests.

Sign a completed package from its generated package directory:

```bash
python scripts/tools/sign_release_archive.py \
  --input /path/to/unsigned.zip --output /path/to/signed.zip \
  --private-key /secure/operator-ed25519.pem --key-id release-key
```

The command accepts an operator-owned unencrypted Ed25519 PEM key. Protect it
with owner-only permissions. It creates a new archive, refuses existing output
paths and never includes the key. Configure the trusted public key on the
upgrade service independently of the uploaded archive.

The `release-signature.json` envelope uses schema
`chuanxu-release-signature/v1`, algorithm `ED25519`, and signed object
`package-files.sha256`. Its digest is the SHA-256 of the exact file-manifest
bytes. Sign the ASCII bytes of `chuanxu-release-manifest/v1`, one newline,
and the 64-character digest. The signature is URL-safe Base64.

The file manifest covers every payload file, including `build-manifest.json`.
It excludes itself and the signature envelope, avoiding a circular digest.
The outer ZIP digest remains the database identity of the staged archive.
Duplicate paths, files outside the package root, altered payloads and untrusted
signatures are rejected. Upgrade preflight, rollout and Skill distribution
recheck the stored archive bytes and current trust key. Skill distribution
requires the verified package version.

Without a trusted key or valid signature, upload remains untrusted and cannot
start a trusted upgrade. Signing alone does not establish release readiness or
complete runtime/Skill delivery acceptance.

## Agent download and acknowledgement

An assigned, active Agent polls `GET /api/agent-gateway/upgrades/skill-pending`
with its instance-bound bearer and `skills.read` scope. Download the exact
archive through `GET /api/agent-gateway/upgrades/{upgrade_id}/skill-archive?skill_version=VERSION`.
The download checks assignment and current server trust and returns no-store ZIP
bytes; it does not extract or execute the package.

Verify those bytes independently with a locally pinned public key:

```bash
python scripts/tools/verify_release_archive.py \
  --input /path/to/downloaded.zip --public-key-file /secure/release-public-key.txt \
  --expected-digest EXPECTED_ZIP_SHA256
```

The public-key file contains URL-safe Base64 of the trusted 32-byte Ed25519 key.
Do not obtain that trust pin from the archive. The verifier checks transport
digest, all manifest entries, signature and the Skill entrypoint without
installing or executing files. Failure exits nonzero and returns a sanitized code.

After successful verification, POST `/api/agent-gateway/upgrades/skill-ack` with
`upgrade_id`, `skill_version`, `verified: true`, the verified `received_digest`
and `safe_point`. Verification defaults to false; old clients must supply the
digest explicitly. Acknowledgement rechecks current server trust and commits
state with its audit. Before a safe point, activation remains OLD_VERSION and
the update stays in the pending inventory. A stale negative acknowledgement
cannot revert an active update. The safe-point value is an authenticated Agent
attestation; it does not independently prove that an external process switched
its installed Skill. Runtime switch verification remains a separate check.

[中文说明](release-signing_zh.md)
