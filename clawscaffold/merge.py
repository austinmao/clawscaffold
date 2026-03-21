"""Profile merge helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from clawscaffold.models import ProfileSpec


class ProfileConflictError(ValueError):
    """Raised when two profiles define incompatible scalar values."""


def _merge_scalar(existing: Any, incoming: Any, rule: str | None) -> Any:
    if rule == "replace":
        return incoming
    if isinstance(existing, bool) and isinstance(incoming, bool):
        return existing or incoming
    if existing != incoming:
        raise ProfileConflictError(f"Conflicting scalar values: {existing!r} != {incoming!r}")
    return existing


def _merge_value(existing: Any, incoming: Any, rule: str | None = None) -> Any:
    if existing is None:
        return incoming
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            child_rule = None
            if isinstance(rule, dict):
                child_rule = rule.get(key)
            merged[key] = _merge_value(merged.get(key), value, child_rule)
        return merged
    if isinstance(existing, list) and isinstance(incoming, list):
        items = incoming + existing if rule == "prepend" else existing + incoming
        deduped: list[Any] = []
        for item in items:
            if item not in deduped:
                deduped.append(item)
        return deduped
    return _merge_scalar(existing, incoming, rule if isinstance(rule, str) else None)


def merge_profiles(
    profiles: Iterable[ProfileSpec],
    priority_order: dict[str, int] | None = None,
) -> dict[str, Any]:
    priority_order = priority_order or {}
    ordered = sorted(
        profiles,
        key=lambda profile: priority_order.get(profile.category, profile.merge_priority),
    )
    merged: dict[str, Any] = {
        "policy": {
            "resource_limits": {},
            "compliance": {},
            "observability": {},
        },
        "operation": {
            "coordination": {},
            "escalation": {},
            "scheduling": {},
            "resilience": {},
        },
        "soul_sections": {},
        "agents_sections": {},
        "heartbeat_items": [],
        "tool_grants": [],
        "config_keys": [],
        "sources": {},
    }
    for profile in ordered:
        contributes = profile.contributes
        rules = profile.merge_rules or {}
        for key in ("policy", "operation", "soul_sections", "agents_sections"):
            if key in contributes:
                merged[key] = _merge_value(merged[key], contributes[key], rules.get(key))
                if isinstance(contributes[key], dict):
                    for child_key in contributes[key]:
                        merged["sources"][f"{key}.{child_key}"] = f"profiles/{profile.id}.yaml"
        if "heartbeat_items" in contributes:
            merged["heartbeat_items"] = _merge_value(
                merged["heartbeat_items"], contributes["heartbeat_items"], rules.get("heartbeat_items")
            )
        if "tool_grants" in contributes:
            merged["tool_grants"] = _merge_value(
                merged["tool_grants"], contributes["tool_grants"], rules.get("tool_grants")
            )
        if "config_keys" in contributes:
            merged["config_keys"] = _merge_value(
                merged["config_keys"], contributes["config_keys"], rules.get("config_keys")
            )
    return merged
