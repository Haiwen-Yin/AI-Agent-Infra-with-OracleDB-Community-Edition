#!/usr/bin/env python3.14
"""Run the v4.4.10 governed model and wallboard flow against live services."""

from __future__ import annotations

import argparse
import base64
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class ProviderState:
    def __init__(self) -> None:
        self.calls = 0
        self.stream_calls = 0
        self.lock = threading.Lock()

    def count(self, stream: bool) -> None:
        with self.lock:
            self.calls += 1
            self.stream_calls += int(stream)


class ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: ProviderState

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - standard-library callback name
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = min(int(self.headers.get("Content-Length", "0")), 1024 * 1024)
        try:
            body = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            self.send_error(400)
            return
        stream = bool(body.get("stream"))
        self.state.count(stream)
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            chunks = (
                {"model": "cx-e2e-model", "choices": [{"delta": {"content": "o"}}]},
                {"model": "cx-e2e-model", "choices": [{"delta": {"content": "k"}}]},
                {"model": "cx-e2e-model", "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}},
            )
            for index, item in enumerate(chunks):
                self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
                self.wfile.flush()
                if index == 0:
                    time.sleep(0.12)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        payload = json.dumps({
            "model": "cx-e2e-model",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class Gate:
    def __init__(self, name: str, url: str, provider_url: str, provider: ProviderState) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.provider_url = provider_url
        self.provider = provider
        self.client = httpx.Client(base_url=self.url, timeout=30, follow_redirects=False)
        self.csrf = ""
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]
        self.checks: dict[str, dict[str, Any]] = {}
        self.metrics: dict[str, Any] = {}

    def record(self, name: str, passed: bool, detail: Any = None) -> None:
        self.checks[name] = {"passed": bool(passed)}
        if detail is not None:
            self.checks[name]["detail"] = detail
        if not passed:
            raise AssertionError(f"{self.name}: {name}: {detail}")

    def request(self, method: str, path: str, *, expected: int = 200, mutation: bool = False, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        if mutation and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        response = self.client.request(method, path, headers=headers, **kwargs)
        if response.status_code != expected:
            raise AssertionError(f"{self.name}: {method} {path} returned {response.status_code}: {response.text[:500]}")
        correlation = response.headers.get("X-Correlation-ID", "")
        self.record(f"correlation:{method}:{path}", len(correlation) >= 8)
        return response

    def login_and_basics(self) -> None:
        started = time.perf_counter()
        health = self.request("GET", "/api/health").json()
        self.metrics["health_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        self.record("health_version", health.get("version") == "4.4.10", health.get("version"))
        ready = self.request("GET", "/api/ready").json()
        self.record("readiness", ready.get("status") in {"ready", "ok"}, ready.get("status"))
        login = self.request("POST", "/api/auth/login", json={"username": "admin", "password": "admin"}).json()
        self.csrf = str(login.get("csrf_token") or "")
        self.record("admin_login", login.get("success") is True and bool(self.csrf))
        capabilities = self.request("GET", "/api/capabilities").json()
        self.record("capabilities", bool(capabilities))

        anonymous = httpx.post(self.url + "/api/model-gateway/quotas", json={}, timeout=10)
        envelope = anonymous.json()
        self.record("anonymous_mutation_denied", anonymous.status_code in {401, 403})
        self.record("error_envelope", all(key in envelope for key in ("code", "message", "correlation_id", "retryable")), sorted(envelope))
        self.record("error_correlation_matches", envelope.get("correlation_id") == anonymous.headers.get("X-Correlation-ID"))

    def routing_and_provider(self) -> str:
        direct_samples = []
        for _ in range(3):
            started = time.perf_counter()
            response = httpx.post(self.provider_url + "/chat/completions", json={
                "model": "cx-e2e-model", "messages": [{"role": "user", "content": "fixed provider baseline"}], "stream": False,
            }, timeout=10)
            response.raise_for_status()
            direct_samples.append((time.perf_counter() - started) * 1000)
        self.metrics["provider_direct_mean_ms"] = round(sum(direct_samples) / len(direct_samples), 3)
        profile_key = f"e2e-{self.name}-{self.run_id}"
        profile = self.request("POST", "/api/llm-provider-profiles", mutation=True, json={
            "profile_key": profile_key,
            "provider_url": self.provider_url,
            "model_id": "cx-e2e-model",
            "api_key": "",
            "approved_for": ["MODEL_GATEWAY"],
            "reason": "v4.4.10 release flow verification",
        }).json()
        profile_id = str(profile["profile_id"])
        probe = self.request("POST", f"/api/llm-provider-profiles/{profile_id}/probe", mutation=True).json()
        self.record("provider_probe", probe.get("status") == "VERIFIED", probe)

        routing = self.request("PUT", "/api/model-gateway/routing", mutation=True, json={
            "profile_id": profile_id,
            "gateway_enabled": True,
            "direct_allowed": True,
            "reason": "parallel direct and governed gateway paths approved for release test",
        }).json()
        self.record("optional_parallel_routing", routing.get("routing_mode") == "OPTIONAL" and routing.get("gateway_enabled") is True and routing.get("direct_allowed") is True)
        self.record("automatic_distribution_url", str(routing.get("gateway_url") or "").endswith("/api/model-gateway/completions"))

        idem = f"gateway-{self.run_id}"
        calls_before = self.provider.calls
        started = time.perf_counter()
        first = self.request("POST", "/api/model-gateway/completions", mutation=True, json={
            "provider_profile_id": profile_id,
            "messages": [{"role": "user", "content": "fixed release probe"}],
            "idempotency_key": idem,
        }).json()
        self.metrics["gateway_non_stream_ms"] = round((time.perf_counter() - started) * 1000, 3)
        self.metrics["gateway_added_ms"] = round(max(0.0, self.metrics["gateway_non_stream_ms"] - self.metrics["provider_direct_mean_ms"]), 3)
        self.record("gateway_usage", first.get("usage", {}).get("total_tokens") == 8, first.get("usage"))
        replay = self.request("POST", "/api/model-gateway/completions", mutation=True, json={
            "provider_profile_id": profile_id,
            "messages": [{"role": "user", "content": "fixed release probe"}],
            "idempotency_key": idem,
        }).json()
        self.record("gateway_transparent_replay", replay.get("replayed") is True and self.provider.calls == calls_before + 1)

        started = time.perf_counter()
        first_delta_ms = None
        stream_body = {
            "provider_profile_id": profile_id,
            "messages": [{"role": "user", "content": "fixed streaming probe"}],
            "stream": True,
            "idempotency_key": f"stream-{self.run_id}",
        }
        with self.client.stream("POST", "/api/model-gateway/completions", headers={"X-CSRF-Token": self.csrf}, json=stream_body) as response:
            self.record("stream_status", response.status_code == 200, response.status_code)
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)
                    if first_delta_ms is None and line.startswith("data:"):
                        first_delta_ms = round((time.perf_counter() - started) * 1000, 3)
        self.metrics["stream_first_delta_ms"] = first_delta_ms
        self.metrics["stream_total_ms"] = round((time.perf_counter() - started) * 1000, 3)
        self.record("stream_incremental_sse", bool(lines) and lines[-1] == "data: [DONE]" and self.provider.stream_calls >= 1, lines[-1:] or None)
        return profile_id

    def quota(self, profile_id: str) -> None:
        warn = self.request("POST", "/api/model-gateway/quotas", mutation=True, json={
            "policy_key": f"warn-{self.run_id}", "scope_type": "PROFILE", "scope_id": profile_id,
            "metric": "TOKEN", "limit_value": "0", "enforcement": "WARN", "window_type": "DAILY",
            "reservation_value": "1", "incomplete_policy": "CHARGE_RESERVED", "reason": "release warning quota",
        }).json()
        self.record("warn_quota_created", warn.get("status") == "ACTIVE", warn)
        response = self.request("POST", "/api/model-gateway/completions", mutation=True, json={
            "provider_profile_id": profile_id, "messages": [{"role": "user", "content": "warn quota probe"}],
            "idempotency_key": f"warn-call-{self.run_id}",
        }).json()
        self.record("warn_quota_allows_dispatch", bool(response.get("quota_warnings")), response.get("quota_warnings"))
        contention_started = time.perf_counter()
        def contend(index: int) -> int:
            result = self.client.post("/api/model-gateway/completions", headers={"X-CSRF-Token": self.csrf}, json={
                "provider_profile_id": profile_id, "messages": [{"role": "user", "content": f"bounded contention {index}"}],
                "idempotency_key": f"contention-{self.run_id}-{index}",
            })
            return result.status_code
        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(contend, range(8)))
        self.metrics["quota_contention_requests"] = len(statuses)
        self.metrics["quota_contention_elapsed_ms"] = round((time.perf_counter() - contention_started) * 1000, 3)
        self.record("quota_contention_atomic", statuses == [200] * 8, statuses)
        status = self.request("GET", "/api/model-gateway/quota-status").json()
        self.record("quota_status", status.get("count", len(status.get("items", []))) >= 1)

        hard_scope = f"hard-{self.run_id}"
        self.request("POST", "/api/model-gateway/quotas", mutation=True, json={
            "policy_key": hard_scope, "scope_type": "AGENT", "scope_id": hard_scope,
            "metric": "TOKEN", "limit_value": "0", "enforcement": "HARD", "window_type": "DAILY",
            "reservation_value": "1", "incomplete_policy": "RELEASE", "reason": "release hard quota",
        })
        calls_before = self.provider.calls
        denied = self.request("POST", "/api/model-gateway/completions", expected=429, mutation=True, json={
            "provider_profile_id": profile_id, "agent_id": hard_scope,
            "messages": [{"role": "user", "content": "must not dispatch"}],
            "idempotency_key": f"hard-call-{self.run_id}",
        })
        self.record("hard_quota_before_dispatch", self.provider.calls == calls_before)
        self.record("hard_quota_error", denied.json().get("code") == "MODEL_QUOTA_EXCEEDED", denied.json())

    def finance(self) -> None:
        invoice_id = f"invoice-{self.run_id}"
        body = {
            "provider_key": "cx-e2e", "external_invoice_id": invoice_id, "currency": "CNY",
            "period_start": "2026-08-01T00:00:00+00:00", "period_end": "2026-08-31T23:59:59+00:00",
            "total_amount": "10.000000", "lines": [{"external_line_id": "line-1", "model_id": "cx-e2e-model", "quantity": "8", "amount": "10.000000"}],
            "reason": "v4.4.10 release invoice verification",
        }
        first = self.request("POST", "/api/model-finance/invoices", mutation=True, json=body).json()
        second = self.request("POST", "/api/model-finance/invoices", mutation=True, json=body).json()
        self.record("invoice_idempotency", first.get("batch_id") == second.get("batch_id") and second.get("idempotent") is True)
        overview = self.request("GET", "/api/model-finance/overview").json()
        line = next(item for item in overview["lines"] if item["batch_id"] == first["batch_id"])
        line_id = str(line["line_id"])
        reconciliation = self.request("POST", f"/api/model-finance/invoice-lines/{line_id}/reconcile", mutation=True, json={
            "usage_id": "", "rule_version": "e2e-v1", "confidence": "1", "reason": "manual provider invoice match",
        }).json()
        self.record("invoice_reconciliation", reconciliation.get("status") == "RECONCILED", reconciliation)
        correction1 = self.request("POST", f"/api/model-finance/invoice-lines/{line_id}/corrections", mutation=True, json={
            "amount_delta": "-0.500000", "reason": "provider credit evidence",
        }).json()
        correction2 = self.request("POST", f"/api/model-finance/invoice-lines/{line_id}/corrections", mutation=True, json={
            "amount_delta": "0.100000", "prior_correction_id": correction1["correction_id"], "reason": "linked correction evidence",
        }).json()
        self.record("linked_invoice_corrections", correction2.get("prior_correction_id") == correction1.get("correction_id"))
        rule_key = f"split-{self.run_id}"
        self.request("POST", "/api/model-finance/allocation-rules", mutation=True, json={
            "rule_key": rule_key, "currency": "CNY", "targets": [
                {"target_type": "COST_CENTER", "target_id": "研发中心", "percentage": "60"},
                {"target_type": "COST_CENTER", "target_id": "安全合规", "percentage": "40"},
            ], "reason": "balanced release allocation",
        })
        allocated = self.request("POST", f"/api/model-finance/INVOICE/{line_id}/allocate", mutation=True, json={"rule_key": rule_key}).json()
        retry = self.request("POST", f"/api/model-finance/INVOICE/{line_id}/allocate", mutation=True, json={"rule_key": rule_key}).json()
        self.record("balanced_allocation", allocated.get("balanced") is True and len(allocated.get("items", [])) == 2)
        self.record("allocation_idempotency", retry.get("idempotent") is True and retry.get("balanced") is True)

    @staticmethod
    def canonical_evidence(body: dict[str, Any]) -> bytes:
        return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()

    def evidence(self) -> None:
        private = Ed25519PrivateKey.generate()
        public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        adapter_id = f"EVA_{self.name}_{self.run_id}"
        adapter = self.request("POST", "/api/model-evidence/adapters", mutation=True, json={
            "adapter_id": adapter_id, "display_name": "Release evidence adapter", "verification_key": public,
            "scopes": ["provider:cx-e2e"],
        }).json()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        canonical = {
            "adapter_id": adapter_id, "key_version": int(adapter["key_version"]), "sequence_no": 1,
            "nonce": uuid.uuid4().hex, "observed_from": (now - timedelta(minutes=1)).isoformat(),
            "observed_to": now.isoformat(), "facts": {"provider_key": "cx-e2e", "request_count": 2, "total_tokens": 16},
        }
        body = {**canonical, "signature": base64.b64encode(private.sign(self.canonical_evidence(canonical))).decode()}
        first = self.request("POST", "/api/model-evidence/ingest", json=body).json()
        retry = self.request("POST", "/api/model-evidence/ingest", json=body).json()
        self.record("signed_evidence", first.get("usage_provenance") == "EXTERNALLY_VERIFIED")
        self.record("evidence_replay_safe", retry.get("idempotent") is True and retry.get("batch_id") == first.get("batch_id"))
        tampered = {**body, "facts": {**body["facts"], "request_count": 3}}
        rejected = self.request("POST", "/api/model-evidence/ingest", expected=401, json=tampered).json()
        self.record("tampered_evidence_rejected", rejected.get("code") == "MODEL_EVIDENCE_REJECTED", rejected)
        revoked = self.request("POST", f"/api/model-evidence/adapters/{adapter_id}/revoke", mutation=True, json={"reason": "release verification complete"}).json()
        self.record("adapter_revocation", revoked.get("changed") == 1, revoked)
        after_revoke = self.request("POST", "/api/model-evidence/ingest", expected=401, json={**body, "sequence_no": 2, "nonce": uuid.uuid4().hex}).json()
        self.record("revoked_adapter_rejected", after_revoke.get("code") == "MODEL_EVIDENCE_REJECTED", after_revoke)

    def wallboard(self) -> None:
        definition_id = f"board-{self.name}-{self.run_id}"
        base = {
            "definition_id": definition_id, "display_name": "发布验收管理大屏",
            "config": {"widgets": ["agent_overview", "runtime", "usage_trend", "coverage", "budget_risk"], "dimensions": ["day", "provider", "provenance"], "refresh_seconds": 15, "locale": "zh-CN", "layout": "EXECUTIVE_GRID"},
            "scope": {}, "reason": "v4.4.10 release wallboard verification",
        }
        v1 = self.request("POST", "/api/wallboard/definitions", mutation=True, json=base).json()
        self.request("POST", f"/api/wallboard/definitions/{v1['version_id']}/publish", mutation=True, json={"reason": "publish verified v1"})
        first = self.request("GET", f"/api/wallboard?definition_id={definition_id}").json()
        self.record("wallboard_v1", int(first.get("definition_version") or 0) == 1 and "agents" in first and "runtime" in first, first.get("definition_version"))
        agents = first.get("agents") or {}
        runtime = first.get("runtime") or {}
        sessions = runtime.get("sessions") or {}
        tasks = runtime.get("tasks") or {}
        total = int(agents.get("total") or 0)
        online = int(agents.get("online") or 0)
        busy = int(agents.get("busy") or 0)
        self.record(
            "wallboard_runtime_population",
            first.get("partial") is False
            and first.get("freshness") == "CURRENT"
            and total > 0
            and 0 <= busy <= online <= total
            and int(sessions.get("active") or 0) > 0
            and int(tasks.get("running_plans") or 0) > 0
            and int(tasks.get("running_loops") or 0) > 0,
            {"agents": agents, "sessions": sessions, "tasks": tasks, "partial": first.get("partial")},
        )
        v2 = self.request("POST", "/api/wallboard/definitions", mutation=True, json={**base, "display_name": "发布验收管理大屏 v2", "reason": "v2 release layout verification"}).json()
        self.request("POST", f"/api/wallboard/definitions/{v2['version_id']}/publish", mutation=True, json={"reason": "publish verified v2"})
        second = self.request("GET", f"/api/wallboard?definition_id={definition_id}").json()
        self.record("wallboard_v2", int(second.get("definition_version") or 0) == 2, second.get("definition_version"))
        self.request("POST", f"/api/wallboard/definitions/{v1['version_id']}/rollback", mutation=True, json={"reason": "verified rollback to v1"})
        rolled = self.request("GET", f"/api/wallboard?definition_id={definition_id}").json()
        self.record("wallboard_rollback", int(rolled.get("definition_version") or 0) == 1, rolled.get("definition_version"))
        started = time.perf_counter()
        for _ in range(5):
            self.request("GET", f"/api/wallboard?definition_id={definition_id}")
        self.metrics["wallboard_mean_ms"] = round((time.perf_counter() - started) * 200, 3)
        self.metrics["wallboard_payload_bytes"] = len(json.dumps(rolled, default=str).encode())

    def run(self) -> dict[str, Any]:
        try:
            self.login_and_basics()
            profile_id = self.routing_and_provider()
            self.quota(profile_id)
            self.finance()
            self.evidence()
            self.wallboard()
        finally:
            self.client.close()
        return {
            "service": self.name, "base_url": self.url, "run_id": self.run_id,
            "passed": all(item["passed"] for item in self.checks.values()),
            "check_count": len(self.checks), "checks": self.checks, "metrics": self.metrics,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="append", default=[], help="NAME=URL; repeat for each database")
    parser.add_argument("--provider-host", default="127.0.0.1")
    parser.add_argument("--provider-port", type=int, default=18110)
    parser.add_argument("--output", type=Path, default=Path("/tmp/v410-full-flow-gate.json"))
    args = parser.parse_args()
    services = args.service or ["oracle=http://127.0.0.1:18100", "pg=http://127.0.0.1:18101", "yashandb=http://127.0.0.1:18102"]
    provider_state = ProviderState()
    ProviderHandler.state = provider_state
    server = ThreadingHTTPServer((args.provider_host, args.provider_port), ProviderHandler)
    worker = threading.Thread(target=server.serve_forever, name="v410-provider-mock", daemon=True)
    worker.start()
    provider_url = f"http://{args.provider_host}:{args.provider_port}/v1"
    results = []
    try:
        for item in services:
            name, url = item.split("=", 1)
            results.append(Gate(name.strip(), url.strip(), provider_url, provider_state).run())
    except Exception as exc:
        results.append({"passed": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        server.shutdown()
        server.server_close()
    payload = {
        "schema": "chuanxu-v410-full-flow/v1", "version": "4.4.10",
        "generated_at": datetime.now(timezone.utc).isoformat(), "provider_calls": provider_state.calls,
        "results": results, "passed": bool(results) and all(item.get("passed") is True for item in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "passed": payload["passed"], "services": len(results), "provider_calls": provider_state.calls}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
