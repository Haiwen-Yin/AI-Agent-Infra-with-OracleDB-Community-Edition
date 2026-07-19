#!/usr/bin/env python3.14
"""AI Agent Infra - Dependency Verifier

Verifies that all packages listed in requirements.txt have corresponding
wheel files in vendor/ directory, with matching versions and platform compatibility.

Usage: python3.14 verify_deps.py
Exit codes: 0 = all OK, 1 = missing/mismatched packages
"""
import os
import sys
import re
import glob

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    vendor_dir = os.path.join(project_dir, "vendor")
    req_file = os.path.join(project_dir, "requirements.txt")

    if not os.path.isdir(vendor_dir):
        print(f"[ERROR] vendor/ directory not found: {vendor_dir}")
        sys.exit(1)

    if not os.path.isfile(req_file):
        print(f"[ERROR] requirements.txt not found: {req_file}")
        sys.exit(1)

    # Parse requirements.txt
    required = {}
    with open(req_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([a-zA-Z0-9_-]+)==(.+)$", line)
            if match:
                name = match.group(1).lower().replace("_", "-")
                version = match.group(2)
                required[name] = version

    # Parse vendor/ wheels
    wheels = {}
    for whl_path in glob.glob(os.path.join(vendor_dir, "*.whl")):
        whl_name = os.path.basename(whl_path)
        parts = whl_name.replace(".whl", "").split("-")
        pkg_name = parts[0].lower().replace("_", "-")
        pkg_version = parts[1]
        wheels[pkg_name] = {"version": pkg_version, "file": whl_name}

    # Verify
    errors = 0
    warnings = 0

    print(f"Verifying {len(required)} required packages against {len(wheels)} wheels in vendor/...")
    print()

    for pkg_name, req_version in sorted(required.items()):
        if pkg_name not in wheels:
            print(f"  MISSING  {pkg_name}=={req_version} (no wheel in vendor/)")
            errors += 1
        elif wheels[pkg_name]["version"] != req_version:
            print(f"  MISMATCH {pkg_name}: required {req_version}, found {wheels[pkg_name]['version']}")
            errors += 1
        else:
            # Check platform compatibility
            whl_file = wheels[pkg_name]["file"]
            if "cp314" not in whl_file and "py3-none-any" not in whl_file:
                print(f"  WARN     {pkg_name}: wheel may not be Python 3.14 compatible ({whl_file})")
                warnings += 1
            elif "manylinux" not in whl_file and "py3-none-any" not in whl_file:
                print(f"  WARN     {pkg_name}: wheel may not be Linux x86_64 compatible ({whl_file})")
                warnings += 1
            else:
                print(f"  OK       {pkg_name}=={req_version}")

    # Check for extra wheels not in requirements
    extra = set(wheels.keys()) - set(required.keys())
    for pkg in sorted(extra):
        print(f"  EXTRA    {pkg}=={wheels[pkg]['version']} (in vendor/ but not in requirements.txt)")
        warnings += 1

    print()
    print(f"Results: {len(required) - errors} OK, {errors} errors, {warnings} warnings")

    if errors > 0:
        print("\n[FAIL] Dependency verification failed. Missing or mismatched packages.")
        sys.exit(1)
    else:
        print("\n[PASS] All dependencies verified successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
