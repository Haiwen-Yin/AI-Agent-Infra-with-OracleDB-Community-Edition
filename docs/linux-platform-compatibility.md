# Linux Platform Compatibility

This document defines the operating-system baseline for v4.4.11 and later.
Full platform functionality, including database services, Agent execution,
embedding/model gateways, and the Linux Runtime Adapter, requires RHEL 9.8+
(Oracle Linux 9.8+), or an equivalent maintained Linux distribution with glibc
2.34 or newer.

## Support levels

### Platform control plane

The Web/API service, database adapters, external-Agent gateway, documentation,
build, and database migration tools require:

- x86_64 Linux with glibc 2.34 or newer;
- Python 3.14 or newer and the package's compatible offline dependencies;
- a supported Oracle, PostgreSQL, or YashanDB client path;
- system service, filesystem, TLS, firewall, and secret-storage controls
  appropriate for the deployment.

Older RHEL/OL 8 hosts and glibc 2.28 environments are unsupported for the
platform baseline and must not be used for release validation.

### Local Agent strong isolation

A host that admits local or platform-managed untrusted Agents MUST pass the
packaged `v411_linux_runtime_isolation_gate.py`. The current tested baseline is:

- x86_64, glibc 2.34 or newer, and Python 3.14 or newer;
- systemd 252 or an independently tested compatible version, with
  `/usr/bin/systemd-run` and `/usr/bin/systemctl`;
- unified cgroup v2 with `cpu`, `memory`, `pids`, and `cpuset` controllers;
- kernel support for user, PID, mount, network, IPC, and UTS namespaces;
- bubblewrap 0.6.3 or an independently tested compatible version;
- libseccomp 2.5.2 or an independently tested compatible `libseccomp.so.2`;
- an enforcing LSM policy, normally SELinux or AppArmor, plus
  `kernel.yama.ptrace_scope=1`, `kernel.unprivileged_bpf_disabled=1`, and
  `fs.suid_dumpable=0`;
- a privileged platform launcher able to create per-Agent identities,
  transient units, namespaces, cgroups, workspaces, and secret mounts.

Default-deny networking is verified. Selective non-empty egress remains
fail-closed until a privileged firewall backend is implemented and evidenced.
Host root and infrastructure administrators remain outside the isolation
threat model.

## Distribution matrix

Distribution names are not security evidence. Every exact image, kernel,
systemd build, security policy, and patch level must pass the gate before being
recorded as supported for strong isolation.

| Distribution family | Control plane | Local strong isolation | Status |
|---|---|---|---|
| Oracle Linux 9.8 x86_64, UEK 6.12 | Supported | Supported | `VERIFIED`, 22/22 gate checks passed |
| RHEL 9, Rocky Linux 9, AlmaLinux 9 | Expected compatible | Gate required | Same platform family; not yet certified by this project |
| CentOS Stream 9 | Development candidate | Gate required | Rolling build is not a production certification target |
| Ubuntu Server 22.04/24.04 LTS | Expected compatible | Gate required | AppArmor and package/path differences require evidence |
| Debian 12/13 | Expected compatible | Gate required | Package versions and LSM policy require evidence |
| SUSE Linux Enterprise Server 15 SP5+ | Expected compatible | Gate required | AppArmor/systemd integration requires evidence |
| openEuler 22.03 LTS SP series and 24.03 LTS | Candidate | Gate required | Prefer unified cgroup v2 images; exact service image must be tested |
| Anolis OS 23 | Candidate | Gate required | Do not infer support from RHEL compatibility claims |
| OpenCloudOS 9 and TencentOS Server 4 | Candidate | Gate required | Kernel and cgroup defaults must be inspected on the target image |
| Kylin Advanced Server V10/V11 | Candidate | Gate required | Product/SP images vary; legacy cgroup v1 images are insufficient |
| UnionTech UOS Server V20/V20E | Candidate | Gate required | Product/update images vary; LSM and cgroup evidence is mandatory |
| Anolis OS 8, RHEL 8 derivatives, older Kylin/UOS images | Unsupported | Unsupported | Below the v4.4.11 glibc/runtime baseline |

"Expected compatible" and "Candidate" are not customer support claims. They
identify the next images to qualify. A later distribution version is never
automatically supported merely because its version number is higher.

## Qualification command

Run from an extracted v4.4.11 package as root on a dedicated non-production
host after installing bubblewrap and libseccomp:

```bash
python3.14 scripts/tools/v411_linux_runtime_isolation_gate.py \
  --base /var/lib/chuanxu-runtime-gate \
  --output /root/v4.4.11-linux-runtime-isolation.json
```

The JSON result must report `passed=true` and
`evidence.enforcement_mode=VERIFIED`. Store only sanitized evidence. Confirm
that no `cx-agent-*` transient unit remains active after the run.

## Deployment decision

- Control plane only, with external Agents: the control-plane baseline is
  sufficient; do not advertise same-host runtime isolation.
- Local trusted development Agent: a weaker host may be accepted only through
  an explicit development policy and remains `UNVERIFIED`.
- Local untrusted Agent, Agent Pool execution, MaaS, or SaaS worker: use a host
  that passes the strong-isolation gate, or use a separately verified container
  or VM adapter. Missing evidence fails closed.
