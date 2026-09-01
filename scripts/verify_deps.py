#!/usr/bin/env python3.14
"""AI Agent Infra - Dependency Verifier

Verifies that all packages listed in requirements.txt have corresponding
wheel files in vendor/ directory, with matching versions and platform compatibility.
Multiple platform wheels for one pinned package/version are supported; the
highest compatible manylinux glibc floor is selected for the current host.

Usage: <python3.14-or-newer> verify_deps.py
Exit codes: 0 = all OK, 1 = missing/mismatched packages
"""
import base64
import csv
import glob
import hashlib
import io
import os
import platform
import re
import sys
import zipfile
from email.parser import Parser

MIN_PYTHON = (3, 14)
# Full platform support baseline: RHEL 9.8+ (Oracle Linux 9.8+) or an equivalent Linux host.
# This corresponds to glibc 2.34+, required by the supported native wheels
# and the Linux runtime-isolation adapter.
MIN_GLIBC = (2, 34)


def _runtime_python() -> tuple[int, int]:
    """Return the active interpreter's major/minor version."""
    return sys.version_info.major, sys.version_info.minor


def _cp_tag_version(tag: str) -> tuple[int, int] | None:
    """Parse CPython tags such as ``cp314`` or ``cp311``."""
    match = re.fullmatch(r"cp(\d)(\d+)", tag)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _glibc_version() -> tuple[int, int] | None:
    """Return the host glibc version when it can be determined."""
    libc, version = platform.libc_ver()
    if libc.lower() != "glibc":
        return None
    match = re.match(r"^(\d+)\.(\d+)", version)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _wheel_platform_floor(filename: str) -> tuple[int, int] | None:
    """Extract a manylinux glibc floor from a wheel filename."""
    match = re.search(r"manylinux_(\d+)_(\d+)", filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    if "manylinux2014" in filename:
        return (2, 17)
    if "manylinux2010" in filename:
        return (2, 12)
    if "manylinux1" in filename:
        return (2, 5)
    return None


def _wheel_filename_parts(filename: str) -> tuple[str, str, str, str, str] | None:
    """Parse the five logical components of a wheel filename.

    Wheel distribution names are normalized before they are written to the
    filename, so keeping the distribution portion as a joined prefix also
    lets the metadata cross-check catch malformed names instead of silently
    treating the second dash-separated token as the version.
    """
    if not filename.endswith(".whl"):
        return None
    parts = filename.removesuffix(".whl").split("-")
    if len(parts) < 5:
        return None
    distribution = "-".join(parts[:-4])
    if not distribution:
        return None
    return distribution, parts[-4], parts[-3], parts[-2], parts[-1]


def _normalize_package_name(value: str) -> str:
    """Apply the PEP 503 normalization used for package identity checks."""
    return re.sub(r"[-_.]+", "-", value).lower()


def _wheel_platform_tag(filename: str) -> str:
    parts = _wheel_filename_parts(filename)
    return parts[4] if parts else ""


def _wheel_architecture_is_compatible(platform_tag: str) -> bool:
    """Reject a wheel built for another OS or CPU architecture."""
    if not platform_tag or platform_tag == "any":
        return True
    tags = platform_tag.split(".")
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        accepted_arches = {"x86_64", "amd64"}
    elif machine in {"aarch64", "arm64"}:
        accepted_arches = {"aarch64", "arm64"}
    else:
        accepted_arches = {machine}
    for tag in tags:
        normalized = tag.lower()
        if normalized.endswith("_x86_64") or normalized.endswith("_amd64"):
            return (
                bool(accepted_arches & {"x86_64", "amd64"})
                and (normalized.startswith("manylinux") or normalized.startswith("linux_"))
            )
        if normalized.endswith("_aarch64") or normalized.endswith("_arm64"):
            return (
                bool(accepted_arches & {"aarch64", "arm64"})
                and (normalized.startswith("manylinux") or normalized.startswith("linux_"))
            )
        if normalized.startswith("manylinux") or normalized.startswith("linux_"):
            # A Linux tag without a recognized architecture is not accepted
            # for a native extension; pure Python wheels use platform `any`.
            continue
        return False
    return False


def _wheel_is_python_compatible(
    filename: str, runtime: tuple[int, int] | None = None
) -> bool:
    """Return whether a wheel can run in the active Python 3.14+ runtime."""
    runtime = runtime or _runtime_python()
    python_tag, abi_tag = _wheel_tags(filename)
    if python_tag == "py3" and abi_tag == "none":
        return True
    expected_tag = f"cp{runtime[0]}{runtime[1]}"
    if python_tag == expected_tag and abi_tag in {expected_tag, "abi3"}:
        return True
    built_for = _cp_tag_version(python_tag)
    # CPython's stable ABI is forward compatible within the same major
    # version, but an exact cp314 extension is not a cp315 extension.
    return bool(
        abi_tag == "abi3"
        and built_for
        and built_for[0] == runtime[0]
        and built_for <= runtime
    )


def _wheel_is_platform_compatible(
    filename: str,
    host_glibc: tuple[int, int] | None,
    runtime: tuple[int, int] | None = None,
) -> bool:
    """Return whether a wheel's declared Linux/glibc floor fits this host.

    Release packages carry one supported wheel per dependency. The verifier
    evaluates its declared glibc floor before installation.
    """
    if not _wheel_is_python_compatible(filename, runtime):
        return False
    if not _wheel_architecture_is_compatible(_wheel_platform_tag(filename)):
        return False
    floor = _wheel_platform_floor(filename)
    if floor and host_glibc and host_glibc < floor:
        return False
    return True


def _wheel_preference(
    candidate: dict, runtime: tuple[int, int] | None = None
) -> tuple[int, int, int, str]:
    """Prefer the highest compatible glibc floor and an exact runtime wheel."""
    floor = candidate.get("floor") or (0, 0)
    filename = candidate["file"]
    runtime = runtime or _runtime_python()
    runtime_tag = f"cp{runtime[0]}{runtime[1]}"
    exact_runtime = 1 if runtime_tag in filename else 0
    manylinux = 1 if "manylinux" in filename else 0
    return floor[0], floor[1], exact_runtime + manylinux, filename


def _wheel_tags(filename: str) -> tuple[str, str]:
    """Return the Python and ABI tags from a normalized wheel filename."""
    parts = _wheel_filename_parts(filename)
    if not parts:
        return "", ""
    return parts[2], parts[3]


def _version_tuple(value: str) -> tuple[int, ...]:
    """Parse the numeric part of a wheel version for local constraint checks."""
    return tuple(int(part) for part in re.findall(r"\d+", value)) or (0,)


def _matches_specifier(version: str, specifier: str) -> bool:
    """Evaluate the simple PEP 440 operators used by bundled dependencies."""
    installed = _version_tuple(version)
    for raw in specifier.split(","):
        item = raw.strip()
        if not item:
            continue
        match = re.match(r"^(==|!=|<=|>=|<|>|~=)\s*([0-9][^,; ]*)", item)
        if not match:
            continue
        operator, expected_text = match.groups()
        expected = _version_tuple(expected_text.rstrip(".*"))
        if operator == "==" and expected_text.endswith(".*"):
            if installed[:len(expected)] != expected:
                return False
        elif operator == "==" and installed != expected:
            return False
        elif operator == "!=" and (
            installed[:len(expected)] == expected
            if expected_text.endswith(".*")
            else installed == expected
        ):
            return False
        elif operator == ">=" and installed < expected:
            return False
        elif operator == "<=" and installed > expected:
            return False
        elif operator == ">" and installed <= expected:
            return False
        elif operator == "<" and installed >= expected:
            return False
        elif operator == "~=" and (installed < expected or installed[:1] != expected[:1]):
            return False
    return True


def _parse_requirement(line: str) -> tuple[str, str, str] | None:
    """Parse a small, offline-safe subset of PEP 508 requirements.

    Generated packages currently use exact shared pins and lower-bound database
    driver requirements.  Keep markers separate so the existing Python-version
    filtering can be applied consistently without importing packaging at boot.
    """
    value = line.split("#", 1)[0].strip()
    if not value:
        return None
    requirement, _, marker = value.partition(";")
    match = re.match(
        r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*((?:(?:===|==|!=|<=|>=|~=|<|>)\s*[^,;\s]+(?:\s*,\s*)?)*)$",
        requirement.strip(),
    )
    if not match:
        return None
    name, specifier = match.groups()
    return name.lower().replace("_", "-"), specifier.strip(), marker.strip()


def _split_marker_expression(expression: str, operator: str) -> list[str]:
    """Split a PEP 508 marker at top-level ``and`` or ``or`` operators."""
    parts: list[str] = []
    start = 0
    depth = 0
    quote = ""
    index = 0
    expression = expression.strip()
    while index < len(expression):
        char = expression[index]
        if quote:
            if char == quote and (index == 0 or expression[index - 1] != "\\"):
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0 and expression[index : index + len(operator)].lower() == operator:
            before = expression[index - 1] if index else " "
            after_index = index + len(operator)
            after = expression[after_index] if after_index < len(expression) else " "
            if before.isspace() and after.isspace():
                parts.append(expression[start:index].strip())
                start = after_index
                index = after_index
                continue
        index += 1
    if parts:
        parts.append(expression[start:].strip())
        return parts
    return [expression]


def _strip_marker_parentheses(expression: str) -> str:
    """Remove balanced outer parentheses without changing quoted values."""
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        quote = ""
        closes_at = None
        for index, char in enumerate(expression):
            if quote:
                if char == quote and (index == 0 or expression[index - 1] != "\\"):
                    quote = ""
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    closes_at = index
                    break
        if closes_at != len(expression) - 1:
            break
        expression = expression[1:-1].strip()
    return expression


def _marker_environment(runtime: tuple[int, int]) -> dict[str, str]:
    """Return the marker values needed by the bundled wheel metadata."""
    return {
        "implementation_name": "cpython",
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_python_implementation": "CPython",
        "platform_system": platform.system(),
        "python_full_version": f"{runtime[0]}.{runtime[1]}.0",
        "python_version": f"{runtime[0]}.{runtime[1]}",
        "sys_platform": sys.platform,
    }


def _marker_atom_applies(atom: str, runtime: tuple[int, int]) -> bool:
    """Evaluate one restricted PEP 508 marker atom.

    Unknown variables are treated as active. This is deliberately fail-closed:
    a future platform marker that the verifier cannot understand must not make
    a mandatory dependency disappear from the closure check.
    """
    atom = _strip_marker_parentheses(atom.strip())
    if not atom:
        return True
    if re.search(r"\bextra\s*(?:==|!=|in|not\s+in)", atom, re.IGNORECASE):
        # No extras are selected by the base offline installation.
        return False
    match = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*(not\s+in|in|===|==|!=|<=|>=|<|>)\s*(['\"])(.*?)\3",
        atom,
        re.IGNORECASE,
    )
    if not match:
        return True
    name, operator, _quote, expected = match.groups()
    actual = _marker_environment(runtime).get(name.lower())
    if actual is None:
        return True
    operator = operator.lower()
    if operator in {"in", "not in"}:
        result = actual in expected
        return not result if operator == "not in" else result
    if name.lower() in {"python_version", "python_full_version"}:
        return _matches_specifier(actual, ("==" if operator == "===" else operator) + expected)
    if operator in {"==", "==="}:
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == ">=":
        return actual >= expected
    if operator == "<=":
        return actual <= expected
    if operator == ">":
        return actual > expected
    if operator == "<":
        return actual < expected
    return True


def _marker_applies_to_runtime(
    marker: str, runtime: tuple[int, int] | None = None
) -> bool:
    """Evaluate the base-install PEP 508 markers used by bundled metadata."""
    runtime = runtime or _runtime_python()
    marker = marker.strip()
    if not marker:
        return True
    marker = _strip_marker_parentheses(marker)
    alternatives = _split_marker_expression(marker, "or")
    return any(
        all(
            _marker_atom_applies(atom, runtime)
            for atom in _split_marker_expression(alternative, "and")
        )
        for alternative in alternatives
    )


def _verify_yaspy_vendor(
    vendor_dir: str, runtime: tuple[int, int] | None = None
) -> tuple[bool, list[str]]:
    """Verify the native YashanDB driver supplied outside the wheelhouse."""
    runtime = runtime or _runtime_python()
    yaspy_dir = os.path.join(vendor_dir, "yaspy")
    native_modules = sorted(glob.glob(os.path.join(yaspy_dir, "yaspy*.so")))
    client_lib_dir = os.path.join(yaspy_dir, "client_lib")
    client_libs = sorted(
        path
        for path in glob.glob(os.path.join(client_lib_dir, "*.so*"))
        if os.path.isfile(path)
    )
    errors: list[str] = []
    if not native_modules:
        errors.append("yaspy native module missing (vendor/yaspy/yaspy*.so)")
    else:
        for path in native_modules:
            filename = os.path.basename(path)
            tag = re.search(r"cpython-(\d+)", filename)
            expected_minor = f"{runtime[0]}{runtime[1]}"
            if tag and tag.group(1) != expected_minor:
                errors.append(
                    f"yaspy native module is not compatible with Python {runtime[0]}.{runtime[1]} ({filename})"
                )
    if not client_libs:
        errors.append("YashanDB client libraries missing (vendor/yaspy/client_lib/*.so*)")
    return not errors, errors


def _read_wheel_metadata(path: str) -> tuple[dict[str, object], list[str]]:
    """Read and integrity-check the metadata files inside a wheel.

    ``pip`` validates enough of this structure during installation that a
    dependency verifier must not silently accept a corrupt or mislabeled wheel
    and then claim an offline release is complete.
    """
    metadata: dict[str, object] = {"requires_dist": []}
    errors: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            metadata_names = [name for name in members if name.endswith("/METADATA")]
            if len(metadata_names) != 1:
                errors.append("wheel must contain exactly one dist-info/METADATA")
                return metadata, errors
            metadata_name = metadata_names[0]
            dist_info = metadata_name.rsplit("/", 1)[0]
            wheel_name = f"{dist_info}/WHEEL"
            record_name = f"{dist_info}/RECORD"
            if wheel_name not in members:
                errors.append("wheel is missing dist-info/WHEEL")
            if record_name not in members:
                errors.append("wheel is missing dist-info/RECORD")
            try:
                metadata_text = archive.read(metadata_name).decode("utf-8")
            except UnicodeDecodeError:
                errors.append("wheel METADATA is not valid UTF-8")
                metadata_text = ""
            headers = Parser().parsestr(metadata_text)
            package_name = headers.get("Name", "").strip()
            package_version = headers.get("Version", "").strip()
            if not package_name:
                errors.append("wheel METADATA is missing Name")
            if not package_version:
                errors.append("wheel METADATA is missing Version")
            metadata.update(
                name=package_name,
                version=package_version,
                requires_python=headers.get("Requires-Python", "").strip(),
                requires_dist=headers.get_all("Requires-Dist", []),
            )
            if record_name in members:
                try:
                    record_text = archive.read(record_name).decode("utf-8")
                    rows = list(csv.reader(io.StringIO(record_text)))
                except (UnicodeDecodeError, csv.Error):
                    rows = []
                    errors.append("wheel dist-info/RECORD is not valid UTF-8 CSV")
                recorded_paths: set[str] = set()
                for row_number, row in enumerate(rows, 1):
                    if len(row) != 3:
                        errors.append(f"wheel RECORD row {row_number} must have three columns")
                        continue
                    relative, digest, size = row
                    if not relative or relative.startswith("/") or ".." in relative.split("/"):
                        errors.append(f"wheel RECORD has invalid path {relative!r}")
                        continue
                    recorded_paths.add(relative)
                    if relative not in members:
                        errors.append(f"wheel RECORD references absent file {relative}")
                        continue
                    data = archive.read(relative)
                    if size and size != str(len(data)):
                        errors.append(f"wheel RECORD size mismatch for {relative}")
                    if digest:
                        algorithm, separator, encoded = digest.partition("=")
                        if not separator or algorithm not in hashlib.algorithms_guaranteed:
                            errors.append(f"wheel RECORD has unsupported hash for {relative}")
                        else:
                            expected = base64.urlsafe_b64encode(
                                hashlib.new(algorithm, data).digest()
                            ).rstrip(b"=").decode("ascii")
                            if expected != encoded:
                                errors.append(f"wheel RECORD hash mismatch for {relative}")
                if record_name not in recorded_paths:
                    errors.append("wheel RECORD must contain its own RECORD entry")
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"wheel archive cannot be read: {type(exc).__name__}")
    return metadata, errors


def _validate_wheel(
    path: str, filename: str, runtime: tuple[int, int] | None = None
) -> list[str]:
    """Cross-check wheel filename, metadata, Python requirement, and RECORD."""
    runtime = runtime or _runtime_python()
    errors: list[str] = []
    parts = _wheel_filename_parts(filename)
    if not parts:
        return ["invalid wheel filename"]
    distribution, version, _python_tag, _abi_tag, platform_tag = parts
    metadata, metadata_errors = _read_wheel_metadata(path)
    errors.extend(metadata_errors)
    metadata_name = str(metadata.get("name", ""))
    metadata_version = str(metadata.get("version", ""))
    if metadata_name and _normalize_package_name(distribution) != _normalize_package_name(metadata_name):
        errors.append(
            f"wheel filename package {distribution!r} disagrees with METADATA Name {metadata_name!r}"
        )
    if metadata_version and metadata_version != version:
        errors.append(
            f"wheel filename version {version!r} disagrees with METADATA Version {metadata_version!r}"
        )
    requires_python = str(metadata.get("requires_python", ""))
    if requires_python and not _matches_specifier(
        f"{runtime[0]}.{runtime[1]}.0", requires_python
    ):
        errors.append(
            f"wheel requires Python {requires_python}, current runtime is {runtime[0]}.{runtime[1]}"
        )
    if not _wheel_architecture_is_compatible(platform_tag):
        errors.append(f"wheel platform tag is incompatible with this host ({platform_tag})")
    return errors


def _metadata_requirements(
    path: str, runtime: tuple[int, int] | None = None
) -> list[tuple[str, str, str]]:
    """Read base (non-extra) Requires-Dist declarations from a wheel."""
    metadata, metadata_errors = _read_wheel_metadata(path)
    if metadata_errors and not metadata.get("requires_dist"):
        return []
    requirements = []
    for value in metadata.get("requires_dist", []):
        if not isinstance(value, str):
            continue
        value = value.strip()
        requirement, _, marker = value.partition(";")
        # Extras are optional and are not part of the offline base runtime.
        if "extra ==" in marker.lower():
            continue
        # Respect the only Python marker forms currently present in the wheelhouse.
        if not _marker_applies_to_runtime(marker, runtime):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", requirement.strip())
        if not match:
            continue
        name, specifier = match.groups()
        requirements.append((name.lower().replace("_", "-"), specifier.strip(), marker.strip()))
    return requirements


def _compatible_wheels(
    wheels: dict[str, list[dict]],
    package_name: str,
    specifier: str,
    host_glibc: tuple[int, int] | None,
    runtime: tuple[int, int],
) -> list[dict]:
    """Return version- and platform-compatible candidates for a dependency."""
    candidates = wheels.get(package_name, [])
    candidates = [
        candidate
        for candidate in candidates
        if not specifier or _matches_specifier(candidate["version"], specifier)
    ]
    return [
        candidate
        for candidate in candidates
        if _wheel_is_platform_compatible(candidate["file"], host_glibc, runtime)
    ]


def _dependency_closure(
    wheels: dict[str, list[dict]],
    roots: dict[str, dict],
    host_glibc: tuple[int, int] | None,
    runtime: tuple[int, int] | None = None,
) -> tuple[list[str], set[str]]:
    """Check mandatory ``Requires-Dist`` dependencies recursively.

    ``requirements.txt`` is intentionally a human-readable direct lock. Pip
    still resolves mandatory transitive dependencies from wheel metadata, so a
    verifier that only checks direct pins can claim success while offline pip
    fails. This traversal mirrors that resolution boundary without importing
    ``packaging`` or making the runtime depend on it.
    """
    runtime = runtime or _runtime_python()
    errors: list[str] = []
    dependency_names: set[str] = set()
    selected = dict(roots)
    queue = list(roots.items())
    visited: set[tuple[str, str]] = set()

    while queue:
        package_name, wheel = queue.pop(0)
        visit_key = (package_name, wheel["file"])
        if visit_key in visited:
            continue
        visited.add(visit_key)
        for dependency_name, specifier, _marker in _metadata_requirements(
            wheel["path"], runtime
        ):
            dependency_names.add(dependency_name)
            candidates = wheels.get(dependency_name, [])
            version_candidates = [
                candidate
                for candidate in candidates
                if not specifier
                or _matches_specifier(candidate["version"], specifier)
            ]
            if dependency_name in selected:
                chosen = selected[dependency_name]
                if specifier and not _matches_specifier(chosen["version"], specifier):
                    errors.append(
                        f"dependency conflict: {package_name}=={wheel['version']} "
                        f"requires {dependency_name}{specifier}, but the selected "
                        f"direct pin is {dependency_name}=={chosen['version']}"
                    )
                continue
            if not version_candidates:
                found = ", ".join(sorted({candidate["version"] for candidate in candidates}))
                detail = f"found {found}" if found else "no wheel in vendor/"
                errors.append(
                    f"missing dependency: {package_name}=={wheel['version']} "
                    f"requires {dependency_name}{specifier} ({detail})"
                )
                continue
            compatible = [
                candidate
                for candidate in version_candidates
                if _wheel_is_platform_compatible(candidate["file"], host_glibc, runtime)
            ]
            if not compatible:
                names = ", ".join(sorted(candidate["file"] for candidate in version_candidates))
                errors.append(
                    f"incompatible dependency: {package_name}=={wheel['version']} "
                    f"requires {dependency_name}{specifier}; candidates: {names}"
                )
                continue
            chosen = max(compatible, key=lambda item: _wheel_preference(item, runtime))
            selected[dependency_name] = chosen
            queue.append((dependency_name, chosen))
    return errors, dependency_names

def main():
    runtime = _runtime_python()
    if runtime < MIN_PYTHON:
        print(
            f"[FAIL] Python 3.14+ is required; current interpreter is "
            f"Python {runtime[0]}.{runtime[1]}.",
            file=sys.stderr,
        )
        sys.exit(1)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    # In the unified source tree this script lives in shared/ and the wheels
    # live beside it.  In a generated archive it lives in scripts/ and the
    # wheels live at the archive root.  Accept both layouts so source checks
    # and package checks exercise the same dependency contract.
    vendor_candidates = [
        os.path.join(project_dir, "vendor"),
        os.path.join(script_dir, "vendor"),
    ]
    vendor_dir = next((path for path in vendor_candidates if os.path.isdir(path)), vendor_candidates[0])
    req_candidates = [
        os.path.join(project_dir, "requirements.txt"),
        os.path.join(script_dir, "requirements.txt"),
    ]
    req_file = next((path for path in req_candidates if os.path.isfile(path)), req_candidates[0])

    if not os.path.isdir(vendor_dir):
        print(f"[ERROR] vendor/ directory not found: {vendor_dir}")
        sys.exit(1)

    if not os.path.isfile(req_file):
        print(f"[ERROR] requirements.txt not found: {req_file}")
        sys.exit(1)

    # Parse requirements.txt.  Do not silently drop lower-bound driver
    # requirements such as oracledb>=4.0.1 or yaspy>=1.2.1.
    required: dict[str, str] = {}
    with open(req_file, encoding="utf-8") as handle:
        for line in handle:
            parsed = _parse_requirement(line)
            if not parsed:
                continue
            name, specifier, marker = parsed
            if not _marker_applies_to_runtime(marker, runtime):
                continue
            required[name] = specifier

    # Parse vendor wheels. Legacy RHEL 8 compatibility artifacts are not
    # release inputs; each pinned dependency uses a current supported artifact.
    wheels: dict[str, list[dict]] = {}
    parse_errors = 0
    for whl_path in glob.glob(os.path.join(vendor_dir, "*.whl")):
        whl_name = os.path.basename(whl_path)
        parts = _wheel_filename_parts(whl_name)
        if not parts:
            print(f"  ERROR    invalid wheel filename: {whl_name}")
            parse_errors += 1
            continue
        distribution, pkg_version, _python_tag, _abi_tag, _platform_tag = parts
        pkg_name = _normalize_package_name(distribution)
        metadata_errors = _validate_wheel(whl_path, whl_name, runtime)
        for message in metadata_errors:
            print(f"  ERROR    {whl_name}: {message}")
        parse_errors += len(metadata_errors)
        wheels.setdefault(pkg_name, []).append(
            {
                "version": pkg_version,
                "file": whl_name,
                "path": whl_path,
                "floor": _wheel_platform_floor(whl_name),
                "metadata_errors": metadata_errors,
            }
        )

    # Verify
    errors = parse_errors
    warnings = 0
    host_glibc = _glibc_version()
    if host_glibc is None or host_glibc < MIN_GLIBC:
        detected = ".".join(str(part) for part in host_glibc) if host_glibc else "unknown"
        print(
            f"[FAIL] RHEL 9.8+ (Oracle Linux 9.8+) or an equivalent Linux host is required for full "
            f"functionality (glibc >= {MIN_GLIBC[0]}.{MIN_GLIBC[1]}); detected {detected}.",
            file=sys.stderr,
        )
        sys.exit(1)
    selected_roots: dict[str, dict] = {}

    wheel_file_count = sum(len(candidates) for candidates in wheels.values())
    print(
        f"Verifying {len(required)} required packages against "
        f"{wheel_file_count} wheel files in vendor/..."
    )
    print()

    for pkg_name, req_version in sorted(required.items()):
        if pkg_name == "yaspy":
            native_ok, native_errors = _verify_yaspy_vendor(vendor_dir, runtime)
            if native_ok:
                print(f"  OK       {pkg_name}{req_version} (native vendor/yaspy)")
            else:
                for message in native_errors:
                    print(f"  MISSING  {message}")
                errors += len(native_errors)
        elif pkg_name not in wheels:
            print(f"  MISSING  {pkg_name}{req_version} (no wheel in vendor/)")
            errors += 1
        else:
            candidates = wheels[pkg_name]
            version_candidates = [
                candidate
                for candidate in candidates
                if not req_version
                or _matches_specifier(candidate["version"], req_version)
            ]
            if not version_candidates:
                found = ", ".join(sorted({c["version"] for c in candidates}))
                print(
                    f"  MISMATCH {pkg_name}: required {req_version}, found {found}"
                )
                errors += 1
                continue
            compatible = [
                candidate
                for candidate in version_candidates
                if _wheel_is_platform_compatible(candidate["file"], host_glibc, runtime)
            ]
            if not compatible:
                names = ", ".join(sorted(c["file"] for c in version_candidates))
                if host_glibc:
                    detail = f"host glibc is {host_glibc[0]}.{host_glibc[1]}"
                else:
                    detail = "host glibc could not be determined"
                print(
                    f"  ERROR    {pkg_name}: no compatible wheel ({detail}); "
                    f"candidates: {names}"
                )
                errors += 1
                continue
            selected = max(compatible, key=lambda item: _wheel_preference(item, runtime))
            selected_roots[pkg_name] = selected
            whl_file = selected["file"]
            if not _wheel_is_python_compatible(whl_file, runtime):
                print(
                    f"  ERROR    {pkg_name}: wheel may not be Python 3.14 compatible "
                    f"({whl_file})"
                )
                errors += 1
            elif "manylinux" not in whl_file and "py3-none-any" not in whl_file:
                print(
                    f"  WARN     {pkg_name}: wheel may not be Linux x86_64 compatible "
                    f"({whl_file})"
                )
                warnings += 1
            else:
                alternatives = len(compatible) - 1
                suffix = f"; {alternatives} alternate wheel(s)" if alternatives else ""
                print(f"  OK       {pkg_name}{req_version} ({whl_file}{suffix})")

    # Check the selected wheel metadata recursively. This catches mandatory
    # transitive packages such as argon2-cffi-bindings even when they are not
    # repeated in requirements.txt.
    closure_errors, dependency_names = _dependency_closure(
        wheels, selected_roots, host_glibc, runtime
    )
    for message in closure_errors:
        print(f"  ERROR    {message}")
    errors += len(closure_errors)

    # Check for extra wheels not in direct requirements or the mandatory
    # dependency closure. Extras remain warnings because adapter packages may
    # intentionally carry platform-specific drivers.
    extra = set(wheels.keys()) - set(required.keys()) - dependency_names
    for pkg in sorted(extra):
        versions = ", ".join(sorted({candidate["version"] for candidate in wheels[pkg]}))
        print(f"  EXTRA    {pkg}=={versions} (in vendor/ but not in requirements.txt)")
        warnings += 1

    print()
    print(f"Results: {max(0, len(required) - errors)} OK, {errors} errors, {warnings} warnings")

    if errors > 0:
        print("\n[FAIL] Dependency verification failed. Missing or mismatched packages.")
        sys.exit(1)
    else:
        print("\n[PASS] All dependencies verified successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
