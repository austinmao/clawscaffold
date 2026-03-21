"""Resolution of canonical target specs plus profiles and tenant overlays."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from clawscaffold.loaders import load_profile_spec, load_target_spec, load_tenant_spec
from clawscaffold.merge import merge_profiles
from clawscaffold.models import ProfileSpec, ResolvedManifest
from clawscaffold.paths import repo_root
from clawscaffold.utils import deep_merge, read_yaml, repo_rel

logger = logging.getLogger(__name__)

_TIER_NAMES = {"basic", "pro", "enterprise"}


def _profile_path(profile_id: str, root: Path) -> Path:
    return root / "profiles" / f"{profile_id}.yaml"


def _overlay_path(kind: str, tenant: str, target_id: str, root: Path) -> Path:
    return root / "tenants" / tenant / "overlays" / f"{kind}s" / f"{target_id}.yaml"


def _is_nested_registry(registry: dict) -> bool | None:
    """Determine if a cognition registry uses nested-by-tier format.

    Returns True if nested (keys are tier names), False if flat (keys are
    cognition keys like "medium/standard/low"), or None if the registry is
    empty or the format cannot be determined.
    """
    if not registry:
        return None
    top_keys = set(registry.keys())
    # If ALL top-level keys are recognised tier names, treat as nested
    if top_keys <= _TIER_NAMES:
        return True
    # If NO top-level keys are tier names, treat as flat
    if not top_keys & _TIER_NAMES:
        return False
    # Ambiguous: some keys are tiers, some are not
    return None


def _resolve_cognition_entry(
    registry: dict,
    key: str,
    subscription_tier: str,
    warnings: list[str],
) -> dict | None:
    """Look up a cognition entry from a flat or nested registry.

    Flat format (backward compat): keys are cognition keys directly.
    Nested format: top-level keys are tier names mapping to cognition-key dicts.
    """
    if not registry or not key:
        if key:
            warnings.append(f"Unresolved cognition registry key: {key}")
        return None

    nested = _is_nested_registry(registry)

    if nested is True:
        tier_map = registry.get(subscription_tier, {})
        if key in tier_map:
            return tier_map[key]
        warnings.append(
            f"Unresolved cognition registry key: {key} "
            f"(tier={subscription_tier})"
        )
        return None

    if nested is False:
        # Flat format — treat entire registry as the lookup table
        if key in registry:
            return registry[key]
        warnings.append(f"Unresolved cognition registry key: {key}")
        return None

    # Ambiguous format
    logger.warning(
        "Cognition registry format could not be determined for tenant; "
        "keys=%s. Attempting flat lookup.",
        list(registry.keys()),
    )
    warnings.append(
        "Cognition registry format ambiguous; attempted flat lookup"
    )
    if key in registry:
        return registry[key]
    warnings.append(f"Unresolved cognition registry key: {key}")
    return None


def resolve_target(
    base_path: str | Path,
    overlay_path: str | Path | None = None,
    profile_paths: Iterable[str | Path] | None = None,
    tenant_path: str | Path | None = None,
) -> ResolvedManifest:
    root = repo_root()
    base_file = Path(base_path)
    target = load_target_spec(base_file)

    tenant_file = Path(tenant_path) if tenant_path else root / "tenants" / target.tenant / "tenant.yaml"
    tenant = load_tenant_spec(tenant_file)

    profile_ids = list(target.policy.get("profiles", []))

    # Auto-inject SaaS-tier profile based on tenant subscription tier (T076)
    # Only inject if profiles directory exists AND tenant explicitly sets subscription_tier
    saas_tier = getattr(tenant, "subscription_tier", None) or tenant.raw.get("subscription_tier")
    if saas_tier and saas_tier != "pro":  # Don't inject for default "pro" — only when explicitly set
        saas_profile_id = f"saas-tier/{saas_tier}"
        if saas_profile_id not in profile_ids:
            saas_profile_path = root / "profiles" / "saas-tier" / f"{saas_tier}.yaml"
            if saas_profile_path.exists():
                profile_ids.insert(0, saas_profile_id)

    profiles: list[ProfileSpec] = []
    if profile_paths is None:
        profile_paths = [_profile_path(profile_id, root) for profile_id in profile_ids]
    for path in profile_paths:
        path_obj = Path(path)
        if path_obj.exists():
            profiles.append(load_profile_spec(path_obj))

    profile_merge = merge_profiles(profiles)
    resolved = deep_merge({"policy": profile_merge["policy"]}, target.to_dict())
    resolved["_profile_sections"] = {
        "soul_sections": profile_merge["soul_sections"],
        "agents_sections": profile_merge["agents_sections"],
        "heartbeat_items": profile_merge["heartbeat_items"],
        "tool_grants": profile_merge["tool_grants"],
        "sources": profile_merge["sources"],
    }

    overlay_file = Path(overlay_path) if overlay_path else _overlay_path(target.kind, target.tenant, target.id, root)
    if overlay_file.exists():
        overlay = read_yaml(overlay_file)
        resolved = deep_merge(resolved, overlay)

    cognition = resolved.get("policy", {}).get("cognition", {})
    key = "/".join(
        [
            cognition.get("complexity", ""),
            cognition.get("cost_posture", ""),
            cognition.get("risk_posture", ""),
        ]
    )
    warnings: list[str] = []
    registry = tenant.cognition_registry
    if not registry:
        registry_path = tenant_file.parent / "cognition-registry.yaml"
        if registry_path.exists():
            registry = read_yaml(registry_path)

    resolved_entry = _resolve_cognition_entry(
        registry, key, tenant.subscription_tier, warnings
    )
    if resolved_entry is not None:
        resolved["resolved_cognition"] = resolved_entry

    # Merge tenant defaults into resolved output
    if tenant.defaults:
        resolved["tenant_defaults"] = tenant.defaults

    resolved["config_policy"] = tenant.config_policy
    resolved["target_source"] = repo_rel(base_file)
    return ResolvedManifest(
        target_id=target.id,
        kind=target.kind,
        target=target,
        resolved=resolved,
        tenant=tenant,
        profiles=profiles,
        warnings=warnings,
    )
