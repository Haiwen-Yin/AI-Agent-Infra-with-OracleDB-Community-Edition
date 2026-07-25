"""Database-independent contracts shared by Graph services and tests."""

from __future__ import annotations

from typing import Iterable, Optional


GRAPH_STATUSES = frozenset({"DRAFT", "VALIDATED", "PUBLISHED", "DEPRECATED", "ARCHIVED"})


def is_valid_status_transition(old: str, new: str) -> bool:
    """Return whether a Graph Version can move between lifecycle states."""
    allowed = {
        "DRAFT": {"VALIDATED", "ARCHIVED"},
        "VALIDATED": {"DRAFT", "PUBLISHED", "ARCHIVED"},
        "PUBLISHED": {"DEPRECATED", "ARCHIVED"},
        "DEPRECATED": {"ARCHIVED"},
        "ARCHIVED": set(),
    }
    old_status = str(old or "").upper()
    new_status = str(new or "").upper()
    return new_status in GRAPH_STATUSES and new_status in allowed.get(old_status, set())


def worker_matches(required_capabilities: Optional[Iterable[str]],
                   worker_capabilities: Optional[Iterable[str]],
                   required_resource_class: Optional[str] = None,
                   worker_runtime: Optional[str] = None) -> bool:
    """Check scheduling eligibility without granting authorization.

    A resource class may be advertised as the Worker runtime or as one of its
    capabilities.  Authorization and policy checks remain separate concerns.
    """
    required = {str(item) for item in (required_capabilities or []) if str(item)}
    advertised = {str(item) for item in (worker_capabilities or []) if str(item)}
    if not required.issubset(advertised):
        return False
    resource_class = str(required_resource_class or "").strip()
    if resource_class and resource_class not in advertised and resource_class != str(worker_runtime or ""):
        return False
    return True
