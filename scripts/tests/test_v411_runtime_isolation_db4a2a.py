from __future__ import annotations

from pathlib import Path
import shutil
import pytest

try:
    from shared.lib.deployment_adapters import TenantRuntimeBinding, tenant_binding_capabilities
    from shared.lib.db4a2a import ContextReference, DB4A2AError, build_dispatch, child_branch_provenance, validate_reference_access
    from shared.lib.runtime_isolation import (IsolationError, RuntimeIsolationContract,
                                              collect_linux_runtime_evidence, detect_drift,
                                              linux_evidence_boundaries, validate_admission)
except ModuleNotFoundError:  # generated edition package
    from lib.deployment_adapters import TenantRuntimeBinding, tenant_binding_capabilities
    from lib.db4a2a import ContextReference, DB4A2AError, build_dispatch, child_branch_provenance, validate_reference_access
    from lib.runtime_isolation import (IsolationError, RuntimeIsolationContract,
                                       collect_linux_runtime_evidence, detect_drift,
                                       linux_evidence_boundaries, validate_admission)


ROOT = Path(__file__).resolve().parents[2]
GENERATED = (ROOT / "build-manifest.json").is_file()


def _container(**kwargs):
    base = dict(
        isolation_level="DEDICATED_CONTAINER", enforcement_mode="VERIFIED",
        runtime_adapter="container", runtime_identity="ctr-1", evidence_ref="ev-1",
        boundaries={"process", "filesystem", "ipc", "network", "resource", "credential"},
        policy_digest="p1", rootfs_digest="r1",
    )
    base.update(kwargs)
    return RuntimeIsolationContract(**base)


def test_external_agent_requires_verified_container_boundary():
    with pytest.raises(IsolationError, match="container or VM"):
        validate_admission(RuntimeIsolationContract("DOMAIN_ISOLATED", "UNVERIFIED", "reference"), external_agent=True)
    assert validate_admission(_container(), external_agent=True)["admitted"] is True


def test_container_evidence_is_complete_and_detects_drift():
    with pytest.raises(IsolationError, match="incomplete"):
        validate_admission(_container(boundaries={"process"}))
    assert detect_drift(_container(), {"runtime_identity": "ctr-2", "policy_digest": "p1", "rootfs_digest": "r1"}) == {
        "drift": True, "mismatches": ["runtime_identity"], "next_state": "DRAIN"
    }


def test_db4a2a_dispatch_uses_reference_and_branch_provenance():
    ref = ContextReference("CTX-1", "sha256-1", 2, "DOMAIN-1")
    envelope = build_dispatch(task_id="TASK-1", context=ref, branch_policy="CHILD_BRANCH_WRITE")
    assert "inline_context" not in envelope
    assert validate_reference_access(envelope, authenticated=True, authorized=True, observed_version=2, observed_digest="sha256-1")["read_allowed"]
    assert child_branch_provenance(envelope, "BRANCH-1")["write_mode"] == "CHILD_BRANCH_ONLY"


def test_db4a2a_rejects_payload_copy_and_stale_snapshot():
    ref = ContextReference("CTX-1", "sha256-1", 1, "DOMAIN-1")
    with pytest.raises(DB4A2AError, match="inline context"):
        build_dispatch(task_id="TASK-1", context=ref, inline_context={"secret": "x"})
    envelope = build_dispatch(task_id="TASK-1", context=ref)
    with pytest.raises(DB4A2AError, match="version mismatch"):
        validate_reference_access(envelope, authenticated=True, authorized=True, observed_version=2, observed_digest="sha256-1")


def test_reference_adapter_and_linux_observation_never_claim_sandbox():
    evidence = collect_linux_runtime_evidence()
    assert evidence["enforcement_mode"] == "UNVERIFIED"
    assert linux_evidence_boundaries(evidence) == frozenset()


def test_linux_adapter_builds_argv_only_default_deny_sandbox(tmp_path):
    try:
        from shared.lib.deployment_adapters import LinuxSandboxSpec, build_linux_sandbox_command
    except ModuleNotFoundError:
        from lib.deployment_adapters import LinuxSandboxSpec, build_linux_sandbox_command
    rootfs = tmp_path / "rootfs"
    work = tmp_path / "work"
    rootfs.mkdir()
    work.mkdir()
    spec = LinuxSandboxSpec("AGENT-1", "INSTANCE-1", ("/bin/true",), 65534, 65534,
                            workdir=str(work), rootfs=str(rootfs))
    command = build_linux_sandbox_command(spec, bwrap=shutil.which("bwrap") or "/usr/bin/bwrap")
    assert command.argv[0].endswith("bwrap")
    assert "--unshare-pid" in command.argv and "--unshare-ipc" in command.argv
    assert "--unshare-net" in command.argv and "--clearenv" in command.argv
    assert "--ro-bind" in command.argv and command.policy_digest.startswith("sha256:")


def test_linux_adapter_rejects_host_root_and_incomplete_evidence():
    try:
        from shared.lib.deployment_adapters import (LinuxSandboxSpec,
                                                    verify_linux_sandbox_evidence)
    except ModuleNotFoundError:
        from lib.deployment_adapters import LinuxSandboxSpec, verify_linux_sandbox_evidence
    with pytest.raises(ValueError, match="host path"):
        LinuxSandboxSpec("AGENT-1", "INSTANCE-1", ("/bin/true",), 1001, 1001,
                         rootfs="/", workdir="/var/lib/ai-agent/work")
    result = verify_linux_sandbox_evidence({
        "backend": "bwrap", "uid": "1001", "gid": "1001",
        "readonly_rootfs": True, "private_proc": True,
        "boundaries": ["process", "filesystem", "ipc", "network"],
    })
    assert result["verified"] is False
    assert result["enforcement_mode"] == "UNVERIFIED"


def test_linux_backend_builds_seccomp_and_bounded_systemd_command():
    try:
        from shared.lib.linux_runtime_backend import build_seccomp_bpf, systemd_command
    except ModuleNotFoundError:
        from lib.linux_runtime_backend import build_seccomp_bpf, systemd_command

    try:
        policy = build_seccomp_bpf(("ptrace", "mount"))
    except RuntimeError as exc:
        if "libseccomp" in str(exc):
            pytest.skip(str(exc))
        raise
    assert policy
    command = systemd_command(
        "cx-agent-test.service", ("/usr/bin/bwrap", "--unshare-net"),
        memory_bytes=64 * 1024 * 1024, pids=16, runtime_seconds=60,
        cpu_quota_percent=75, uid=10001, gid=10002,
    )
    joined = " ".join(command)
    for value in (
        "MemoryMax=67108864", "TasksMax=16", "RuntimeMaxSec=60",
        "CPUQuota=75%", "User=10001", "Group=10002", "NoNewPrivileges=yes",
    ):
        assert value in joined


def test_linux_backend_fails_closed_for_unconfigured_egress():
    try:
        from shared.lib.linux_runtime_backend import LinuxRuntimeBackend, LinuxRuntimeBackendError
    except ModuleNotFoundError:
        from lib.linux_runtime_backend import LinuxRuntimeBackend, LinuxRuntimeBackendError

    with pytest.raises(LinuxRuntimeBackendError, match="egress allowlist backend"):
        LinuxRuntimeBackend().start(
            "exec-1", agent_id="agent-1", instance_id="instance-1",
            sandbox_argv=("/bin/true",), memory_bytes=64 * 1024 * 1024,
            pids=16, runtime_seconds=60, cpu_quota_percent=100,
            policy_digest="sha256:policy", rootfs_digest="sha256:rootfs",
            egress=("10.0.0.0/8",), uid=10001, gid=10001,
        )


def test_linux_evidence_selects_actual_sandbox_process_from_cgroup():
    try:
        from shared.lib.linux_runtime_backend import select_sandbox_process
    except ModuleNotFoundError:
        from lib.linux_runtime_backend import select_sandbox_process

    names = ("pid", "mnt", "net", "user", "ipc", "uts")
    host = {name: f"{name}:[1]" for name in names}
    parent = dict(host)
    child = {name: f"{name}:[2]" for name in names}
    statuses = {101: {"Seccomp": "0"}, 202: {"Seccomp": "2"}}
    namespaces = {101: parent, 202: child}
    selected, status, selected_namespaces = select_sandbox_process(
        (101, 202), host,
        status_reader=lambda pid: statuses[pid],
        namespace_reader=lambda pid, name: namespaces[pid][name],
    )
    assert selected == 202
    assert status["Seccomp"] == "2"
    assert all(selected_namespaces[name] != host[name] for name in names)


def test_tenant_runtime_binding_requires_all_boundaries_and_rejects_runtime_socket():
    binding = TenantRuntimeBinding(
        target_type="kubernetes", tenant_id="tenant-1", namespace="agent-tenant-1",
        service_account="agent-runtime", network_policy="deny-default",
        resource_quota="tenant-quota", storage_binding="pvc-tenant-1",
        kms_key_ref="kms://tenant-1",
    )
    capabilities = tenant_binding_capabilities(binding)
    assert capabilities["required_bindings_present"] is True
    assert capabilities["vendor_provisioning_verified"] is False
    with pytest.raises(ValueError, match="runtime socket"):
        TenantRuntimeBinding(
            target_type="SAAS", tenant_id="tenant-1", namespace="agent-tenant-1",
            service_account="agent-runtime", network_policy="deny-default",
            resource_quota="tenant-quota", storage_binding="pvc-tenant-1",
            kms_key_ref="kms://tenant-1", socket_mounts=("/var/run/docker.sock",),
        )


def test_v411_gateway_exposes_drift_heartbeat_and_lifecycle_routes():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "web_app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/gateway/runtime-heartbeat")' in source
    assert 'def runtime_isolation_contract_transition(' in source
    assert "heartbeat_contract(" in source
    assert '@app.get("/api/graph-assurance/invariants")' in source
    assert '@app.get("/api/graph-assurance/evidence")' in source


def test_web_startup_rejects_untracked_listener_and_rechecks_child_liveness():
    source = (Path(__file__).resolve().parents[1] / "start_web_server.sh").read_text(
        encoding="utf-8"
    )
    assert "already serving an untracked process" in source
    assert "sleep 0.5" in source
    assert source.count("if is_running; then") >= 3


def test_db4a2a_branch_call_matches_branch_service_contract():
    import inspect
    try:
        from shared.lib import branch_api, db4a2a
    except ModuleNotFoundError:
        from lib import branch_api, db4a2a

    parameters = inspect.signature(branch_api.fork_branch).parameters
    assert {"workspace_id", "fork_context_id", "branch_name", "branch_type", "agent_id"} <= set(parameters)
    source = inspect.getsource(db4a2a.create_dispatch_branch)
    assert 'branch_type="DB4A2A"' in source
    assert "created_by_agent" not in source


@pytest.mark.skipif(GENERATED, reason="cross-adapter static contract runs in the unified source gate")
def test_v411_static_contract_covers_all_database_adapters():
    from pathlib import Path
    import live_db_validator

    root = Path(__file__).resolve().parents[2]
    for database in ("oracle", "pg", "yashandb"):
        deploy = root / "adapters" / database / "deploy"
        scripts = [deploy / name for name in live_db_validator.V411_MIGRATION_SCRIPTS]
        if database == "pg":
            scripts.extend((deploy / "51_v4_4_9_identity_boundary_repair.sql",
                            deploy / "53_v4_4_9_pg_runtime_boundary.sql"))
        result = live_db_validator.validate_v411_static_contract(database, scripts, "enterprise")
        assert result["passed"] is True, result


def test_manifest_import_uses_controlled_capability_in_both_http_stacks():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root / "web_app.py", root / "visualization" / "server.py"):
        source = path.read_text(encoding="utf-8")
        assert "normalized.startswith(\"/api/graphs/\") and normalized.endswith(\"/import\")" in source or \
               "normalized.startswith('/api/graphs/') and normalized.endswith('/import')" in source
        assert "normalized.endswith(\"/fork\")" in source or "normalized.endswith('/fork')" in source
        assert "/api/branches/" not in source.split("def _graph_operation_capability", 1)[1].split("return None", 1)[0]


def test_reference_worker_cannot_admit_stronger_runtime_claim():
    try:
        from shared.lib.deployment_adapters import reference_adapters
    except ModuleNotFoundError:
        from lib.deployment_adapters import reference_adapters

    evidence = reference_adapters()["LOCAL_MANAGED"].evidence({
        "execution_id": "EXE-1", "target_id": "DT-1",
        "isolation_level": "DEDICATED_CONTAINER",
    }).evidence
    contract = RuntimeIsolationContract(
        "DEDICATED_CONTAINER", evidence["enforcement_mode"], "LOCAL_MANAGED",
        evidence_ref="runtime-execution:EXE-1", boundaries=frozenset(evidence["boundaries"]),
    )
    with pytest.raises(IsolationError):
        validate_admission(contract, requested_level="DEDICATED_CONTAINER",
                           adapter_capabilities=evidence)


def test_checkpoint_fork_auto_replay_allows_only_explicit_safe_effect_classes():
    try:
        from shared.lib import graph_runtime
    except ModuleNotFoundError:
        from lib import graph_runtime

    safe = graph_runtime.fork_replay_decision({"nodes": [
        {"node_key": "read", "side_effect_class": "NONE"},
        {"node_key": "notify", "side_effect_class": "IDEMPOTENT_EXTERNAL"},
    ]})
    transactional = graph_runtime.fork_replay_decision({"nodes": [
        {"node_key": "write", "side_effect_class": "DB_TRANSACTIONAL"},
    ]})
    assert safe["allowed"] is True
    assert transactional["allowed"] is False
    assert transactional["non_repeatable_nodes"] == ["write"]
