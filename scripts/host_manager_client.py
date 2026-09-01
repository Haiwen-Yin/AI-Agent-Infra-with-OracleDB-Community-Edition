#!/usr/bin/env python3.14
"""Send one structured request to the local Host Manager socket."""

from __future__ import annotations

import argparse
import socket
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/chuanxu/host-manager.sock")
    args = parser.parse_args()
    payload = sys.stdin.buffer.readline(1024 * 1024)
    if not payload:
        raise SystemExit("a JSON request line is required")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(args.socket)
        client.sendall(payload.rstrip(b"\n") + b"\n")
        response = b""
        while not response.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            response += chunk
    sys.stdout.buffer.write(response)


if __name__ == "__main__":
    main()
