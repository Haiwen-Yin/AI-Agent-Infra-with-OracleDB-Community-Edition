#!/usr/bin/env python3.14
"""Create a bounded, redacted support bundle from POC evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECRET_RE = re.compile(
    r'(?i)("?(?:password|api[_-]?key|secret[_-]?key|token)"?\s*[:=]\s*)["\']?[^,\s"\'}]+',
)
MAX_LOG_BYTES = 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"ObjectRequired:{path.name}")
    return payload


def _config_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {"file": path.name, "present": path.exists()}
    if not path.exists():
        return summary
    try:
        raw = _safe_json(path)
        summary["sections"] = sorted(raw)
        summary["encrypted_sections"] = sorted(
            name for name, value in raw.items() if isinstance(value, dict) and value.get("_encrypted")
        )
        summary["database_fields"] = sorted((raw.get("database") or {}).keys())
        summary["mode"] = oct(path.stat().st_mode & 0o777)
    except Exception as exc:
        summary["error_type"] = type(exc).__name__
    return summary


def _redact_log(path: Path) -> tuple[str, dict[str, Any]]:
    raw = path.read_bytes()[:MAX_LOG_BYTES]
    text = raw.decode("utf-8", errors="replace")
    redacted = SECRET_RE.sub(r"\1<REDACTED>", text)
    metadata = {"file": path.name, "bytes_read": len(raw), "truncated": path.stat().st_size > len(raw)}
    return redacted, metadata


def build_bundle(output: Path, manifest: Path, poc: Path, readiness: Path | None = None,
                 configs: list[Path] | None = None, logs: list[Path] | None = None,
                 manifest_output: Path | None = None) -> dict[str, Any]:
    payloads = [("release-manifest.json", manifest), ("poc-evidence.json", poc)]
    if readiness is not None:
        payloads.append(("poc-readiness.json", readiness))
    entries: dict[str, bytes] = {}
    for name, path in payloads:
        if not path.exists():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        entries[name] = data

    configs = configs or []
    config_summaries = [_config_summary(path) for path in configs]
    entries["config-summary.json"] = (json.dumps(config_summaries, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    environment = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "cwd_recorded": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    entries["environment.json"] = (json.dumps(environment, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    log_metadata = []
    for index, path in enumerate(logs or []):
        if not path.exists() or not path.is_file():
            continue
        content, metadata = _redact_log(path)
        name = f"logs/{index:02d}-{path.name}"
        entries[name] = content.encode("utf-8")
        log_metadata.append(metadata)
    entries["README.txt"] = (
        "AI Agent Infra POC support bundle\n"
        "This bundle contains sanitized evidence and bounded logs only.\n"
        "Original configuration files and credentials are intentionally excluded.\n"
    ).encode("ascii")

    files = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            data = entries[name]
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
            files.append({"file": name, "bytes": len(data), "sha256": _sha256(data)})
    report = {
        "schema": "ai-agent-infra-support-bundle/v1",
        "version": _safe_json(manifest).get("version"),
        "generated_at": environment["generated_at"],
        "passed": True,
        "archive": output.name,
        "archive_sha256": _sha256(output.read_bytes()),
        "files": files,
        "logs": log_metadata,
        "config_files_excluded": True,
        "secret_values_excluded": True,
        "max_log_bytes": MAX_LOG_BYTES,
    }
    destination = manifest_output or output.with_suffix(".json")
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a redacted POC support bundle.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--poc", type=Path, required=True)
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--config", type=Path, action="append", default=[])
    parser.add_argument("--log", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path)
    args = parser.parse_args(argv)
    report = build_bundle(
        args.output, args.manifest, args.poc, args.readiness,
        args.config, args.log, args.manifest_output,
    )
    print(json.dumps({"output": str(args.output), "sha256": report["archive_sha256"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
