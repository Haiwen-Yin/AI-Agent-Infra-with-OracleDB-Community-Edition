# Cryptography Wheel Policy - AI Agent Infra with DB v4.4.11

The platform uses `cryptography==49.0.0` for configuration and credential
encryption. v4.4.11 and later target RHEL 9.8+ (Oracle Linux 9.8+), or an
equivalent maintained Linux distribution with glibc 2.34 or newer.

## Release wheel

Each release ships exactly one cryptography wheel:

`cryptography-49.0.0-cp311-abi3-manylinux_2_34_x86_64.whl`

The `cp311-abi3` tag is compatible with CPython 3.14 and later CPython 3.x
versions supporting the stable ABI. The former RHEL 8/glibc 2.28
`manylinux_2_28` source-built wheel is retired and must not be added to a
release archive.

## Validation

Run the normal offline dependency gate on the supported host:

```bash
python3.14 shared/verify_deps.py
```

The gate rejects hosts below glibc 2.34, foreign platform tags, incompatible
Python tags, metadata mismatches, and incomplete transitive dependencies. Do
not rename wheels or replace the system glibc to bypass the check.

## Historical artifacts

Older release notes may mention the RHEL 8 compatibility build because it was
used during prior validation. Those artifacts are historical records only and
are not valid inputs for v4.4.11+ packaging.
