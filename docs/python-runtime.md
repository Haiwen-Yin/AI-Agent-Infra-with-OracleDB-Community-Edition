# Python Runtime Policy - AI Agent Infra with DB v4.3.1

The release requires an accessible CPython **3.14 or newer** interpreter.
There is no preferred vendor or installation source.
The package never assumes that `/home/linuxbrew/.linuxbrew` is visible or
executable; this matters when a build/test sandbox hides host paths.

## Select The Runtime

At the package root, the bundled resolver checks the executable by running it
and verifying `sys.version_info`:

```bash
source scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
"$PYTHON_BIN" --version
```

Set `PYTHON_BIN` explicitly when the interpreter is outside `PATH`:

```bash
export PYTHON_BIN=/path/to/python3.14
source scripts/python_runtime.sh
PYTHON_BIN="$(cx_resolve_python "$PYTHON_BIN")"
cx_prepare_python_environment "$PYTHON_BIN"
```

Shell command substitution runs the resolver in a subshell. For scripts that
need to execute several commands without repeating the library-path detail,
use the bundled wrapper after resolving the interpreter:

```bash
PYTHON_BIN="$(cx_resolve_python)"
cx_run_python "$PYTHON_BIN" --version
cx_run_python "$PYTHON_BIN" -m pytest scripts/tests/ -q
```

`cx_run_python` prepares an adjacent `libpython` directory for each child
process. This is useful for sandbox-visible or relocatable Python trees and
does not assume Linuxbrew or any other vendor-specific installation path.

The resolver also detects a relocatable Python installation whose `libpython`
shared library is stored in the installation's adjacent `lib/` or `lib64/`
directory. It adds that directory to `LD_LIBRARY_PATH` for the current shell,
so a sandbox-visible runtime can be used without changing the host's system
libraries. The same behavior applies to the package start and offline install
scripts.

An explicit but inaccessible or older interpreter fails closed. Without an
explicit value, the resolver scans `PATH`, tests `python3.N` candidates, and
selects the highest executable version at or above 3.14. It does not fall back
to an older `python3` binary.

## Sandbox And Deployment

The sandbox used by a build agent is not the customer host. A permission error
when it tries to execute a host-only path means that the sandbox cannot cross
that path boundary; it does not prove that the customer host lacks Python.
Run source tests with an interpreter made visible to the sandbox and pass it
through `PYTHON_BIN`. Run customer deployment with the same resolver on the
customer host. No sandbox exception or glibc replacement is required. A
sandbox restriction on one host-only path is an execution-environment issue,
not a Python version requirement.

## Wheel Compatibility

The minimum version and wheel compatibility are separate checks. A CPython
extension wheel tagged `cp314` is for CPython 3.14; an `abi3` wheel can be
used by a later CPython 3.x minor version when its stable ABI permits it.
`verify_deps.py` checks the active interpreter and rejects incompatible wheels.
It also follows every selected wheel's mandatory `Requires-Dist` metadata,
including platform markers, so a transitive package cannot be missing while
the direct pins appear complete. Optional extras are not part of the base
offline installation; an unknown marker is treated as required and blocks
verification until it is understood.
For every bundled wheel it also cross-checks the filename against `METADATA`,
checks `Requires-Python`, rejects foreign operating-system or architecture
tags, and validates the hashes and sizes recorded in `dist-info/RECORD`.
The current YashanDB package contains a `yaspy` CPython 3.14 native module;
Python 3.15+ requires a matching driver module before that edition can run.

The offline installer also checks the host glibc floor. The release may carry
both the upstream `cryptography==49.0.0` `manylinux_2_34` wheel and a verified
source-built `manylinux_2_28` wheel. The latter must be built on a glibc 2.28
baseline and verified with `auditwheel`; it must never be created by renaming
the upstream wheel. The current v4.3.1 package contains both verified wheels,
so `verify_deps.py` selects the glibc 2.28 artifact on this host and the
`manylinux_2_34` artifact on newer systems.

The release build runs this offline dependency gate by default after all six
archives are generated. `--skip-dependency-validate` is available only for
development diagnostics when a wheelhouse is intentionally incomplete; it does
not make the generated archives releasable.
