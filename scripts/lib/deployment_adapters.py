"""Reference DeploymentTarget adapters for v4.3.6.

These adapters define the product boundary for customer infrastructure.  They
do not make vendor-specific calls and never grant authority from a callback.
Each customer connector can implement the same lifecycle with its own
credential and network policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Protocol


TARGET_TYPES = frozenset({
    "LOCAL_MANAGED", "REMOTE_WORKER", "CONTAINER_MANAGED", "WEBHOOK_MANAGED",
})


@dataclass(frozen=True)
class AdapterResult:
    operation: str
    target_type: str
    status: str
    evidence: Dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(Protocol):
    target_type: str

    def prepare(self, execution: Dict[str, Any]) -> AdapterResult: ...
    def activate(self, execution: Dict[str, Any]) -> AdapterResult: ...
    def health(self, execution: Dict[str, Any]) -> AdapterResult: ...
    def cancel(self, execution: Dict[str, Any], reason: str) -> AdapterResult: ...
    def revoke(self, execution: Dict[str, Any], reason: str) -> AdapterResult: ...
    def evidence(self, execution: Dict[str, Any]) -> AdapterResult: ...


class ReferenceRuntimeAdapter:
    """A non-networking lifecycle reference with fail-closed evidence."""

    def __init__(self, target_type: str) -> None:
        if target_type not in TARGET_TYPES:
            raise ValueError("unsupported deployment target type")
        self.target_type = target_type

    def _result(self, operation: str, status: str, execution: Dict[str, Any]) -> AdapterResult:
        return AdapterResult(
            operation=operation,
            target_type=self.target_type,
            status=status,
            evidence={
                "execution_id": str(execution.get("execution_id") or ""),
                "target_id": str(execution.get("target_id") or ""),
                "isolation_level": str(execution.get("isolation_level") or ""),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "authority": "database",
            },
        )

    def prepare(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("PREPARE", "READY", execution)

    def activate(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("ACTIVATE", "ACTIVE", execution)

    def health(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("HEALTH", "UNKNOWN", execution)

    def cancel(self, execution: Dict[str, Any], reason: str) -> AdapterResult:
        if len(str(reason or "").strip()) < 3:
            raise ValueError("cancellation reason is required")
        return self._result("CANCEL", "CANCELLED", execution)

    def revoke(self, execution: Dict[str, Any], reason: str) -> AdapterResult:
        if len(str(reason or "").strip()) < 3:
            raise ValueError("revocation reason is required")
        return self._result("REVOKE", "REVOKED", execution)

    def evidence(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("EVIDENCE", "RECORDED", execution)


def reference_adapters() -> Dict[str, RuntimeAdapter]:
    return {target_type: ReferenceRuntimeAdapter(target_type) for target_type in sorted(TARGET_TYPES)}


def describe_reference_adapters() -> list[Dict[str, Any]]:
    return [
        {
            "target_type": target_type,
            "reference": True,
            "network_calls": False,
            "lifecycle": ["prepare", "activate", "health", "cancel", "revoke", "evidence"],
            "security_note": "权限、凭证和最终状态仍由平台数据库与 Gateway 决定",
        }
        for target_type in sorted(TARGET_TYPES)
    ]
