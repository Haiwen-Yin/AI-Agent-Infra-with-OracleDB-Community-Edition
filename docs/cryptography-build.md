# cryptography Wheel Policy - AI Agent Infra with DB v4.4.1

The platform uses `cryptography==49.0.0` for local AES-256-GCM configuration
and credential encryption. The upstream Linux wheel currently carries the
`manylinux_2_34` tag. It cannot load on RHEL 8, whose glibc baseline is 2.28.

## Wheel Set

The release may contain both wheels for the same package and version:

| Wheel | Intended host |
|---|---|
| `cryptography-49.0.0-cp314-abi3-manylinux_2_28_x86_64.whl` | RHEL 8 / glibc 2.28; built from source on the RHEL 8 baseline |
| `cryptography-49.0.0-cp311-abi3-manylinux_2_34_x86_64.whl` | Newer Linux systems with glibc 2.34 or later; upstream binary wheel |

The `cp311-abi3` tag is intentional: it is compatible with CPython 3.14.
`pip` selects the compatible wheel from `vendor/`, and `scripts/verify_deps.py`
performs the same glibc-floor check before installation. The requirement stays
`cryptography==49.0.0`; the release does not downgrade the cryptographic
library merely to accommodate an older operating system.

The current v4.3.2 package contains both wheels and has been verified on the
RHEL 8/glibc 2.28 baseline. Do not deploy a package on RHEL 8 by renaming an
incompatible wheel or by substituting an older cryptography release.
The same offline gate currently requires the pinned `argon2-cffi==25.1.0`
transitive closure and `fastapi==0.120.4` wheel; those files must be supplied
from the same approved wheelhouse before the Web runtime can be started.

## Building The RHEL 8 Wheel

Build the compatibility wheel on RHEL 8 or an equivalent glibc 2.28 builder.
Do not replace the host's `/lib64/libc.so.6`. The builder needs an accessible
Python 3.14+ runtime, a Rust toolchain compatible with cryptography 49,
`maturin`, `cffi`, `auditwheel`, and OpenSSL 3 development headers/libraries.
RHEL 8's system OpenSSL 1.1.1 is not the supported build target for this
release; use an isolated OpenSSL 3 installation if required by the build
toolchain.

For the validated x86_64 RHEL 8 build, compile that isolated OpenSSL with
4 KiB ELF load-segment alignment, for example:

```bash
LDFLAGS="-Wl,-z,max-page-size=0x1000 -Wl,-z,common-page-size=0x1000" \\
  ./Configure linux-x86_64 -fPIC shared no-tests \\
  --prefix=/opt/openssl-3.0.21 --openssldir=/opt/openssl-3.0.21/ssl
```

Verify the resulting shared libraries with `readelf -l` and confirm each
`LOAD` segment reports `Align 0x1000` before building the Python wheel. This
avoids a dynamic-loader failure on the RHEL 8 baseline when the OpenSSL build
uses a 2 MiB maximum page-size alignment.

The source distribution must be obtained from the approved internal mirror or
PyPI mirror and verified before use:

```bash
sha256sum --check cryptography-49.0.0.tar.gz.sha256
# Use any accessible Python 3.14+ executable; the installation source is not prescribed.
export PYTHON_BIN=/path/to/python3.14
bash scripts/tools/build_cryptography_wheel.sh \
  /path/to/cryptography-49.0.0.tar.gz \
  /path/to/ai-agent-infra/shared/vendor
```

The script uses `auditwheel repair --plat manylinux_2_28_x86_64`. It fails if
the binary references newer GLIBC symbols, so a wheel built on a newer host
cannot be relabeled as an RHEL 8 wheel. After copying the wheel into
`shared/vendor/`, copy the exact pinned `argon2-cffi`,
`argon2-cffi-bindings`, `annotated-doc`, and `fastapi` wheels into the same
directory, then run
the six-edition build and package checks. The default build dependency gate
must pass; `--skip-dependency-validate` is diagnostic only.

## Newer Operating Systems

Customers on glibc 2.34 or later do not need to rebuild cryptography. They may
use the upstream `manylinux_2_34` wheel already present in `vendor/`. If an
internal security policy requires a locally built wheel, it must still pass
`auditwheel show` and be tagged for its real glibc baseline.

Do not manually rename a wheel, use the RHEL 8 wheel on an older-than-2.28
system, or replace system glibc. A host below glibc 2.28 requires a separate
older-baseline build and is outside the v4.3.0 validated target.
