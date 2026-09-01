import zipfile

import verify_deps


def _metadata_wheel(tmp_path, package, version, requirements=()):
    filename = f"{package.replace('-', '_')}-{version}-py3-none-any.whl"
    path = tmp_path / filename
    metadata = [
        "Metadata-Version: 2.1",
        f"Name: {package}",
        f"Version: {version}",
        *(f"Requires-Dist: {requirement}" for requirement in requirements),
        "",
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{package.replace('-', '_')}-{version}.dist-info/METADATA",
            "\n".join(metadata),
        )
    return {
        "version": version,
        "file": filename,
        "path": str(path),
        "floor": None,
    }


def test_platform_floor_understands_legacy_and_modern_manylinux_tags():
    assert verify_deps._wheel_platform_floor("pkg-1-cp314-cp314-manylinux2014_x86_64.whl") == (2, 17)
    assert verify_deps._wheel_platform_floor("pkg-1-cp314-cp314-manylinux_2_28_x86_64.whl") == (2, 28)
    assert verify_deps._wheel_platform_floor("pkg-1-py3-none-any.whl") is None


def test_full_platform_baseline_is_glibc_2_34():
    assert verify_deps.MIN_GLIBC == (2, 34)
    legacy = "cryptography-49.0.0-cp314-abi3-manylinux_2_28_x86_64.whl"
    current = "cryptography-49.0.0-cp311-abi3-manylinux_2_34_x86_64.whl"
    assert verify_deps._wheel_is_platform_compatible(current, (2, 34))
    assert not verify_deps._wheel_is_platform_compatible(current, (2, 33))
    assert verify_deps._wheel_is_platform_compatible(legacy, (2, 34))


def test_newer_host_can_use_the_upstream_cryptography_wheel():
    newer_host = (2, 35)
    upstream = "cryptography-49.0.0-cp311-abi3-manylinux_2_34_x86_64.whl"

    assert verify_deps._wheel_is_platform_compatible(upstream, newer_host)


def test_platform_check_rejects_a_native_wheel_for_another_operating_system():
    windows = "package-1.0-cp314-cp314-win_amd64.whl"
    assert not verify_deps._wheel_is_platform_compatible(windows, (2, 28), (3, 14))


def test_python_wheel_tags_follow_the_active_python_minor():
    abi3 = "cryptography-49.0.0-cp311-abi3-manylinux_2_28_x86_64.whl"
    exact_314 = "pydantic_core-2.46.4-cp314-cp314-manylinux_2_17_x86_64.whl"
    exact_315 = "pydantic_core-2.46.4-cp315-cp315-manylinux_2_17_x86_64.whl"

    assert verify_deps._wheel_is_python_compatible(abi3, (3, 15))
    assert not verify_deps._wheel_is_python_compatible(exact_314, (3, 15))
    assert verify_deps._wheel_is_python_compatible(exact_315, (3, 15))


def test_marker_evaluator_handles_platform_and_extra_markers():
    assert not verify_deps._marker_applies_to_runtime(
        "sys_platform == 'win32' and python_version >= '3.14'", (3, 14)
    )
    assert not verify_deps._marker_applies_to_runtime(
        "platform_python_implementation == 'CPython' and extra == 'cli'", (3, 14)
    )
    assert verify_deps._marker_applies_to_runtime(
        "sys_platform != 'win32' and python_version >= '3.14'", (3, 14)
    )


def test_dependency_closure_fails_for_missing_transitive_wheel(tmp_path):
    root = _metadata_wheel(
        tmp_path,
        "root-pkg",
        "1.0.0",
        ["argon2-cffi-bindings>=21.2.0"],
    )
    errors, dependencies = verify_deps._dependency_closure(
        {"root-pkg": [root]},
        {"root-pkg": root},
        (2, 28),
        (3, 14),
    )

    assert dependencies == {"argon2-cffi-bindings"}
    assert len(errors) == 1
    assert "argon2-cffi-bindings>=21.2.0" in errors[0]
    assert "no wheel in vendor/" in errors[0]


def test_dependency_closure_respects_direct_pin_and_platform_markers(tmp_path):
    root = _metadata_wheel(
        tmp_path,
        "root-pkg",
        "1.0.0",
        [
            "dep-pkg>=2.0.0",
            "windows-pkg>=1.0.0; sys_platform == 'win32'",
        ],
    )
    direct = _metadata_wheel(tmp_path, "dep-pkg", "1.0.0")
    errors, dependencies = verify_deps._dependency_closure(
        {"root-pkg": [root], "dep-pkg": [direct]},
        {"root-pkg": root, "dep-pkg": direct},
        (2, 28),
        (3, 14),
    )

    assert dependencies == {"dep-pkg"}
    assert len(errors) == 1
    assert "selected direct pin" in errors[0]


def test_yaspy_native_module_requires_matching_cpython_minor(tmp_path):
    vendor = tmp_path / "vendor" / "yaspy" / "client_lib"
    vendor.mkdir(parents=True)
    (vendor / "libyas_infra.so").write_bytes(b"native")
    (vendor.parent / "yaspy.cpython-314-x86_64-linux-gnu.so").write_bytes(b"native")

    assert verify_deps._verify_yaspy_vendor(str(tmp_path / "vendor"), (3, 14))[0]
    ok, errors = verify_deps._verify_yaspy_vendor(str(tmp_path / "vendor"), (3, 15))
    assert not ok
    assert "Python 3.15" in " ".join(errors)


def test_wheel_metadata_validation_rejects_missing_integrity_files(tmp_path):
    wheel = _metadata_wheel(tmp_path, "demo-pkg", "1.0.0")
    errors = verify_deps._validate_wheel(
        wheel["path"], wheel["file"], (3, 14)
    )
    assert "wheel is missing dist-info/WHEEL" in errors
    assert "wheel is missing dist-info/RECORD" in errors
