#!/usr/bin/env python3.14
"""Unix-socket service wrapper for the root-owned Host Manager."""

from __future__ import annotations

import argparse
import grp
import json
import logging
import os
from pathlib import Path
import socketserver

try:
    from lib.host_manager import HostManager, HostManagerConfig
except ImportError:
    from shared.lib.host_manager import HostManager, HostManagerConfig


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        request: object = {}
        try:
            request = json.loads(self.rfile.readline(1024 * 1024))
            response = self.server.manager.execute(request)  # type: ignore[attr-defined]
        except Exception as exc:
            response = {"status": "FAILED", "error": type(exc).__name__, "detail": str(exc)}
        logging.info(
            "host_manager action=%s request_id=%s status=%s",
            str(request.get("action") if isinstance(request, dict) else "invalid")[:32],
            str(request.get("request_id") if isinstance(request, dict) else "invalid")[:128],
            response.get("status"),
        )
        self.wfile.write((json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/chuanxu/host-manager.sock")
    parser.add_argument("--runtime-root", default="/var/lib/chuanxu-runtime")
    parser.add_argument("--uid-min", type=int, default=200000)
    parser.add_argument("--uid-max", type=int, default=299999)
    parser.add_argument("--socket-group", default="chuanxu-admin")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Host Manager service must run as root")
    socket_path = Path(args.socket)
    socket_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(socket_path), Handler) as server:
        server.manager = HostManager(HostManagerConfig(Path(args.runtime_root), args.uid_min, args.uid_max))
        os.chown(socket_path, 0, grp.getgrnam(args.socket_group).gr_gid)
        os.chmod(socket_path, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    main()
