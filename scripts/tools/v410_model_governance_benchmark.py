#!/usr/bin/env python3.14
"""Collect bounded, sanitized v4.4.10 wallboard performance evidence."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentage)))
    return round(ordered[position], 3)


def session(url: str) -> httpx.Client:
    client = httpx.Client(base_url=url.rstrip("/"), timeout=30)
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    response.raise_for_status()
    return client


def run_service(name: str, url: str, workers: int, requests_per_worker: int) -> dict[str, Any]:
    sample = session(url)
    wallboard = sample.get("/api/wallboard")
    wallboard.raise_for_status()
    usage = sample.get("/api/model-usage/summary")
    usage.raise_for_status()
    board_payload = wallboard.json()
    usage_payload = usage.json()
    sample.close()

    def worker(_index: int) -> tuple[list[float], list[int], list[int]]:
        client = session(url)
        latencies: list[float] = []
        statuses: list[int] = []
        sizes: list[int] = []
        try:
            for _ in range(requests_per_worker):
                started = time.perf_counter()
                response = client.get("/api/wallboard")
                latencies.append((time.perf_counter() - started) * 1000)
                statuses.append(response.status_code)
                sizes.append(len(response.content))
        finally:
            client.close()
        return latencies, statuses, sizes

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        batches = list(executor.map(worker, range(workers)))
    elapsed = time.perf_counter() - started
    latencies = [value for batch in batches for value in batch[0]]
    statuses = [value for batch in batches for value in batch[1]]
    sizes = [value for batch in batches for value in batch[2]]
    reported_requests = sum(int(item.get("requests") or 0) for item in usage_payload.get("items", []))
    runtime = board_payload.get("runtime") or {}
    representative_volume = {
        "reported_gateway_usage_records": reported_requests,
        "registered_agents": int((board_payload.get("agents") or {}).get("total") or 0),
        "active_sessions": int((runtime.get("sessions") or {}).get("active") or 0),
        "running_plans": int((runtime.get("tasks") or {}).get("running_plans") or 0),
        "running_loops": int((runtime.get("tasks") or {}).get("running_loops") or 0),
        "external_verified_requests": int((board_payload.get("coverage") or {}).get("externally_verified_requests") or 0),
    }
    return {
        "service": name,
        "base_url": url,
        "requests": len(statuses),
        "workers": workers,
        "passed": bool(statuses) and all(status == 200 for status in statuses)
        and board_payload.get("partial") is False
        and representative_volume["reported_gateway_usage_records"] > 0
        and representative_volume["registered_agents"] > 0
        and representative_volume["active_sessions"] > 0
        and representative_volume["running_plans"] > 0
        and representative_volume["running_loops"] > 0,
        "error_count": sum(status != 200 for status in statuses),
        "elapsed_ms": round(elapsed * 1000, 3),
        "throughput_requests_per_second": round(len(statuses) / elapsed, 3) if elapsed else 0,
        "latency_ms": {"mean": round(statistics.fmean(latencies), 3), "p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95), "max": round(max(latencies), 3)},
        "payload_bytes": {"mean": round(statistics.fmean(sizes), 1), "max": max(sizes)},
        "representative_volume": representative_volume,
        "boundary": "Current populated test volume and bounded concurrent refresh; not a capacity certification.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--requests-per-worker", type=int, default=10)
    parser.add_argument("--flow-evidence", type=Path)
    parser.add_argument("--output", type=Path, default=Path("/tmp/v410-model-governance-benchmark.json"))
    args = parser.parse_args()
    services = args.service or ["oracle=http://127.0.0.1:18100", "pg=http://127.0.0.1:18101", "yashandb=http://127.0.0.1:18102"]
    results = [run_service(*item.split("=", 1), max(1, min(args.workers, 32)), max(1, min(args.requests_per_worker, 100))) for item in services]
    flow_metrics: dict[str, Any] = {}
    if args.flow_evidence and args.flow_evidence.is_file():
        source = json.loads(args.flow_evidence.read_text(encoding="utf-8"))
        flow_metrics = {str(item.get("service")): item.get("metrics", {}) for item in source.get("results", []) if item.get("service")}
    payload = {
        "schema": "chuanxu-v410-model-governance-benchmark/v1", "version": "4.4.10",
        "generated_at": datetime.now(timezone.utc).isoformat(), "results": results,
        "gateway_flow_metrics": flow_metrics, "passed": all(item["passed"] for item in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "passed": payload["passed"], "services": len(results)}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
