#!/usr/bin/env python3.14
"""Complete a one-time Agent Pool host bootstrap and optional heartbeats.

This tool is executed on the target host after an administrator has created a
one-time bootstrap token in the Dashboard.  It never receives database
credentials and does not persist the token.  The platform activates the node
only after this receipt and an audited Agent Pool shared-storage binding.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - operator-supplied platform URL
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise SystemExit(f"platform rejected node bootstrap: HTTP {exc.code}") from exc
    except URLError as exc:
        raise SystemExit(f"could not reach platform: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Chuanxu Agent Pool node bootstrap")
    parser.add_argument("--platform-url", required=True, help="HTTPS URL of the Chuanxu platform")
    parser.add_argument("--onboarding-id", required=True)
    parser.add_argument("--token", required=True, help="single-use token; never write it to disk")
    parser.add_argument("--shared-path", default="", help="local path of the already-mounted Pool shared directory")
    parser.add_argument("--agent-info-path", default="", help="local root for Agent metadata and per-Agent runtime subdirectories")
    parser.add_argument("--runtime-version", default="v4.4.11")
    parser.add_argument("--host-manager-socket", default="/run/chuanxu/host-manager.sock")
    parser.add_argument("--host-evidence-dir", default="/var/lib/chuanxu-runtime/evidence")
    parser.add_argument("--heartbeat-seconds", type=int, default=0, help="send periodic heartbeats after activation")
    args = parser.parse_args()
    base = args.platform_url.rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://127.0.0.1") and not base.startswith("http://localhost"):
        raise SystemExit("platform URL must use HTTPS outside local development")
    shared = str(Path(args.shared_path).resolve()) if args.shared_path else ""
    if shared and not Path(shared).is_dir():
        raise SystemExit("shared path does not exist on this host")
    agent_info = str(Path(args.agent_info_path).resolve()) if args.agent_info_path else ""
    if agent_info and not Path(agent_info).is_dir():
        raise SystemExit("Agent information path does not exist on this host")
    request = {"protocol": "chuanxu-host-manager/v1", "action": "preflight",
               "request_id": "pool-checkin-preflight", "idempotency_key": f"pool-checkin-{args.onboarding_id}"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(args.host_manager_socket)
            client.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8"))
            response = b""
            while not response.endswith(b"\n"):
                chunk = client.recv(65536)
                if not chunk:
                    break
                response += chunk
        preflight = json.loads(response.decode("utf-8")).get("result") or {}
    except (OSError, ValueError) as exc:
        raise SystemExit("Host Manager preflight is unavailable") from exc
    evidence_dir = Path(args.host_evidence_dir)
    try:
        lifecycle = json.loads((evidence_dir / "host-verification.json").read_text(encoding="ascii"))
        root_state = json.loads((evidence_dir / "root-ssh-state.json").read_text(encoding="ascii"))
        recovery_channel = (evidence_dir / "recovery-channel").read_text(encoding="utf-8").strip()
    except (OSError, ValueError) as exc:
        raise SystemExit("complete lifecycle verification and root SSH handoff before node check-in") from exc
    payload: dict[str, object] = {
        "token": args.token,
        "runtime_version": args.runtime_version,
        "hostname": socket.gethostname(),
        "shared_path": shared,
        "agent_info_path": agent_info,
        "runtime_preflight": preflight,
        "lifecycle_passed": lifecycle.get("passed") is True and lifecycle.get("lifecycle_passed") is True,
        "root_remote_login": root_state.get("root_remote_login"),
        "recovery_channel": recovery_channel,
    }
    result = post(f"{base}/api/agent-pool/node-onboardings/{args.onboarding_id}/check-in", payload)
    print(json.dumps(result, ensure_ascii=True))
    if args.heartbeat_seconds <= 0:
        return 0
    interval = max(15, min(args.heartbeat_seconds, 3600))
    while True:
        time.sleep(interval)
        result = post(
            f"{base}/api/agent-pool/node-onboardings/{args.onboarding_id}/heartbeat",
            {"token": args.token, "runtime_version": args.runtime_version},
        )
        print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    sys.exit(main())
