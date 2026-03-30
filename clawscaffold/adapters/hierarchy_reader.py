"""Read config/paperclip-agents.yaml and merge overrides onto catalog specs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .catalog_reader import CatalogAgent

# ---------------------------------------------------------------------------
# Public dict-based API (simpler interface for callers that don't use
# CatalogAgent dataclasses)
# ---------------------------------------------------------------------------

_OVERRIDE_FIELDS = frozenset(
    {"reportsTo", "budgetMonthlyCents", "role", "lifecycle_bridge", "heartbeatEnabled"}
)


def resolve_agent_key(agent_id: str) -> str:
    """Convert a catalog agent ID to a short Paperclip key.

    Examples::

        resolve_agent_key("executive/cmo") -> "cmo"
        resolve_agent_key("campaigns/campaign-orchestrator") -> "campaign-orchestrator"
    """
    return agent_id.split("/")[-1]


def _gateway_id_to_catalog_id(gateway_id: str) -> str:
    """Convert a Paperclip agentId to a catalog ID.

    The agentId format is ``agents-<domain>-<name>`` where ``<domain>`` is a
    single-segment identifier and ``<name>`` may itself contain hyphens.

    Examples::

        "agents-executive-cmo"                        -> "executive/cmo"
        "agents-campaigns-campaign-orchestrator"      -> "campaigns/campaign-orchestrator"
        "agents-engineering-frontend-engineer"        -> "engineering/frontend-engineer"
    """
    # Strip the leading "agents-" prefix
    without_prefix = gateway_id.removeprefix("agents-")
    # Replace only the *first* hyphen with "/" to separate domain from name
    return without_prefix.replace("-", "/", 1)


def read_hierarchy(repo_root: Path) -> dict[str, dict]:
    """Read ``config/paperclip-agents.yaml`` and return overrides keyed by short key.

    The short key is derived from the entry's ``agentId`` field using
    :func:`resolve_agent_key` applied to the equivalent catalog ID.

    Args:
        repo_root: Repository root directory containing ``config/``.

    Returns:
        A dict mapping short Paperclip key (e.g. ``"cmo"``,
        ``"campaign-orchestrator"``) to the raw YAML entry dict.  Returns an
        empty dict if the file is missing or unparseable.
    """
    config_path = repo_root / "config" / "paperclip-agents.yaml"
    if not config_path.is_file():
        return {}

    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return {}

    result: dict[str, dict] = {}
    for entry in raw.get("agents", []):
        gateway_id = entry.get("agentId", "")
        if not gateway_id:
            continue
        catalog_id = _gateway_id_to_catalog_id(gateway_id)
        key = resolve_agent_key(catalog_id)
        result[key] = entry

    return result


def merge_hierarchy(
    catalog_agents: list[dict],
    hierarchy: dict[str, dict],
) -> list[dict]:
    """Merge Paperclip hierarchy overrides onto catalog agent specs.

    Each catalog agent dict is expected to have at least an ``"id"`` field
    (e.g. ``"campaigns/campaign-orchestrator"``).  The short key derived from
    that ID is used to look up the matching hierarchy entry.

    Override fields applied (when present in the hierarchy entry):

    * ``reportsTo`` — resolved to a short key via :func:`resolve_agent_key`
      when the value contains a ``/`` (catalog ID format); otherwise used as-is.
    * ``budgetMonthlyCents``
    * ``role``
    * ``lifecycle_bridge``
    * ``heartbeatEnabled``

    A ``paperclip_key`` field is added to every returned agent dict.

    Args:
        catalog_agents: List of catalog agent dicts (plain ``dict``, not
            :class:`CatalogAgent` dataclasses).
        hierarchy: Dict returned by :func:`read_hierarchy` — keyed by short key.

    Returns:
        New list of merged agent dicts (originals are not mutated).
    """
    merged: list[dict] = []

    for agent in catalog_agents:
        agent_id: str = agent.get("id", "")
        key = resolve_agent_key(agent_id)
        override = hierarchy.get(key, {})

        # Start with a shallow copy so we never mutate the input
        result: dict[str, Any] = dict(agent)
        result["paperclip_key"] = key

        for field in _OVERRIDE_FIELDS:
            if field in override:
                value = override[field]
                if field == "reportsTo" and isinstance(value, str) and "/" in value:
                    value = resolve_agent_key(value)
                result[field] = value

        merged.append(result)

    return merged


# Map org_level to Paperclip role
ORG_LEVEL_TO_ROLE: dict[str, str] = {
    "executive": "pm",
    "director": "pm",
    "manager": "pm",
    "lead": "engineer",
    "specialist": "engineer",
    "": "engineer",
}


@dataclass
class MergedAgent:
    """Agent spec merged with Paperclip hierarchy overrides."""

    id: str  # catalog ID (e.g. "executive/cmo")
    key: str  # Paperclip short key (e.g. "cmo")
    gateway_agent_id: str  # gateway ID (e.g. "agents-executive-cmo")
    title: str
    display_name: str
    description: str
    emoji: str
    role: str  # Paperclip role: "pm" | "engineer"
    reports_to_key: str | None  # resolved Paperclip key
    budget_monthly_cents: int
    heartbeat_enabled: bool
    lifecycle_bridge: str
    timeout_sec: int
    org_level: str
    manages: list[str]


def _catalog_id_to_key(catalog_id: str) -> str:
    """Convert catalog ID to Paperclip short key.

    "executive/cmo" -> "cmo"
    "campaigns/campaign-orchestrator" -> "campaign-orchestrator"
    """
    return catalog_id.split("/")[-1]


def _catalog_id_to_gateway_id(catalog_id: str) -> str:
    """Convert catalog ID to OpenClaw gateway agent ID.

    "executive/cmo" -> "agents-executive-cmo"
    """
    return "agents-" + catalog_id.replace("/", "-")


def read_hierarchy_config(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Read config/paperclip-agents.yaml and index by agentId."""
    config_path = repo_root / "config" / "paperclip-agents.yaml"
    if not config_path.is_file():
        return {}

    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for entry in raw.get("agents", []):
        agent_id = entry.get("agentId", "")
        if agent_id:
            result[agent_id] = entry
    return result


def merge_agents(
    catalog_agents: list[CatalogAgent],
    repo_root: Path,
) -> list[MergedAgent]:
    """Merge catalog agents with hierarchy config overrides.

    Returns list of MergedAgent sorted by org_level (executive first) then alphabetical.
    """
    hierarchy = read_hierarchy_config(repo_root)

    # Build lookup: gateway_id -> hierarchy entry
    merged: list[MergedAgent] = []

    for agent in catalog_agents:
        key = _catalog_id_to_key(agent.id)
        gateway_id = _catalog_id_to_gateway_id(agent.id)

        # Find matching hierarchy entry
        override = hierarchy.get(gateway_id, {})

        # Resolve role
        role = override.get("role", ORG_LEVEL_TO_ROLE.get(agent.org_level, "engineer"))

        # Resolve reportsTo: override takes precedence, then catalog
        reports_to_raw = override.get("reportsTo", agent.reports_to)
        reports_to_key: str | None = None
        if reports_to_raw:
            # Could be a catalog ID ("executive/cmo") or already a key
            reports_to_key = (
                _catalog_id_to_key(reports_to_raw) if "/" in reports_to_raw else reports_to_raw
            )

        merged.append(
            MergedAgent(
                id=agent.id,
                key=key,
                gateway_agent_id=gateway_id,
                title=override.get("title", agent.title),
                display_name=override.get("name", agent.display_name),
                description=agent.description,
                emoji=agent.emoji,
                role=role,
                reports_to_key=reports_to_key,
                budget_monthly_cents=override.get("budgetMonthlyCents", 0),
                heartbeat_enabled=override.get("heartbeatEnabled", False),
                lifecycle_bridge=override.get("lifecycle_bridge", "not_enrolled"),
                timeout_sec=override.get("timeoutSec", 60),
                org_level=agent.org_level,
                manages=agent.manages,
            )
        )

    # Sort: executive first, then alphabetical by key
    level_order = {"executive": 0, "director": 1, "manager": 2, "lead": 3, "specialist": 4}
    return sorted(merged, key=lambda a: (level_order.get(a.org_level, 99), a.key))
