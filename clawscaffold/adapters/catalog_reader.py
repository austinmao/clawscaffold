"""Read catalog/agents/**/*.yaml and return parsed agent specs."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CatalogAgent:
    """Parsed agent spec from catalog."""

    id: str  # e.g. "executive/cmo"
    title: str
    description: str
    display_name: str
    emoji: str
    department: str
    business_function: str
    org_level: str
    reports_to: str | None
    manages: list[str]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def _iter_catalog_yaml(catalog_dir: Path) -> list[Path]:
    """Return sorted YAML paths from catalog_dir, skipping non-spec files."""
    result: list[Path] = []
    for yaml_path in sorted(catalog_dir.rglob("*.yaml")):
        if yaml_path.stem.endswith((".interview", ".review")):
            continue
        if ".interview." in yaml_path.name or ".review." in yaml_path.name:
            continue
        result.append(yaml_path)
    return result


def read_catalog_agents(
    repo_root: Path,
    filter_pattern: str | None = None,
) -> list[CatalogAgent]:
    """Read all catalog/agents/**/*.yaml and return parsed specs.

    Args:
        repo_root: Repository root directory.
        filter_pattern: Optional glob pattern to match against agent IDs
                        (e.g. "executive/*", "sales/*").

    Returns:
        List of CatalogAgent dataclasses sorted by ID.
    """
    catalog_dir = repo_root / "catalog" / "agents"
    if not catalog_dir.is_dir():
        return []

    agents: list[CatalogAgent] = []
    for yaml_path in _iter_catalog_yaml(catalog_dir):
        # Derive agent ID from path: catalog/agents/executive/cmo.yaml -> executive/cmo
        rel = yaml_path.relative_to(catalog_dir)
        agent_id = str(rel.with_suffix(""))

        # Apply filter
        if filter_pattern and not fnmatch.fnmatch(agent_id, filter_pattern):
            continue

        try:
            raw = yaml.safe_load(yaml_path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            print(f"WARNING: Failed to read {yaml_path}: {exc}")
            continue

        if raw.get("kind") != "agent":
            continue

        identity = raw.get("identity", {})
        org = raw.get("org", {})

        agents.append(
            CatalogAgent(
                id=raw.get("id", agent_id),
                title=raw.get("title", agent_id.split("/")[-1].replace("-", " ").title()),
                description=raw.get("description", ""),
                display_name=identity.get("display_name", raw.get("title", "")),
                emoji=identity.get("emoji", ""),
                department=org.get("department", ""),
                business_function=org.get("business_function", ""),
                org_level=org.get("org_level", ""),
                reports_to=org.get("reports_to"),
                manages=org.get("manages", []),
                raw=raw,
            )
        )

    return sorted(agents, key=lambda a: a.id)


def read_catalog(
    repo_root: Path,
    filter_pattern: str | None = None,
) -> list[dict[str, Any]]:
    """Read all catalog/agents/**/*.yaml and return parsed specs as plain dicts.

    Each returned dict contains the following keys:

    - ``id`` (str): agent identifier, e.g. ``"executive/cmo"``
    - ``title`` (str)
    - ``description`` (str)
    - ``org`` (dict): keys ``reports_to``, ``org_level``, ``business_function``,
      ``manages`` (list[str])
    - ``identity`` (dict): keys ``display_name``, ``emoji``
    - ``heartbeat`` (dict): keys ``enabled`` (bool), ``cadence_minutes`` (int)

    Args:
        repo_root: Repository root directory.
        filter_pattern: Optional fnmatch pattern matched against the agent ``id``
                        (e.g. ``"executive/*"``, ``"sales/*"``).  When *None* all
                        agents are returned.

    Returns:
        List of dicts sorted alphabetically by ``id``.
    """
    catalog_dir = repo_root / "catalog" / "agents"
    if not catalog_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for yaml_path in _iter_catalog_yaml(catalog_dir):
        rel = yaml_path.relative_to(catalog_dir)
        agent_id = str(rel.with_suffix(""))

        if filter_pattern and not fnmatch.fnmatch(agent_id, filter_pattern):
            continue

        try:
            raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            print(f"WARNING: Failed to read {yaml_path}: {exc}")
            continue

        if raw.get("kind") != "agent":
            continue

        identity_raw = raw.get("identity") or {}
        org_raw = raw.get("org") or {}
        heartbeat_raw = (raw.get("agent") or {}).get("heartbeat") or {}

        results.append(
            {
                "id": raw.get("id", agent_id),
                "title": raw.get("title", agent_id.split("/")[-1].replace("-", " ").title()),
                "description": raw.get("description", ""),
                "org": {
                    "reports_to": org_raw.get("reports_to"),
                    "org_level": org_raw.get("org_level", ""),
                    "business_function": org_raw.get("business_function", ""),
                    "manages": list(org_raw.get("manages") or []),
                },
                "identity": {
                    "display_name": identity_raw.get("display_name", raw.get("title", "")),
                    "emoji": identity_raw.get("emoji", ""),
                },
                "heartbeat": {
                    "enabled": bool(heartbeat_raw.get("enabled", False)),
                    "cadence_minutes": int(heartbeat_raw.get("cadence_minutes", 0)),
                },
            }
        )

    return sorted(results, key=lambda d: d["id"])
