"""Org chart graph validation for agent hierarchy.

Validates reports_to relationships, derives manages[] lists,
detects cycles/orphans, validates escalation chains and
coordination pattern consistency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clawscaffold.paths import repo_root


@dataclass
class GraphAuditResult:
    """Result of a full graph audit."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    derived_manages: dict[str, list[str]] = field(default_factory=dict)
    agent_count: int = 0
    edge_count: int = 0


def _load_agent_specs(catalog_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all agent canonical specs from catalog/agents/."""
    agents: dict[str, dict[str, Any]] = {}
    agents_dir = catalog_dir / "agents"
    if not agents_dir.exists():
        return agents
    for path in sorted(agents_dir.rglob("*.yaml")):
        try:
            with open(path, encoding="utf-8") as fh:
                spec = yaml.safe_load(fh)
            if isinstance(spec, dict) and spec.get("kind") == "agent":
                agents[spec["id"]] = spec
        except Exception:
            continue
    return agents


def derive_manages(catalog_dir: Path | None = None) -> dict[str, list[str]]:
    """Derive manages[] lists from reports_to relationships.

    Returns a dict mapping agent_id -> list of agent_ids that report to it.
    """
    base = catalog_dir or (repo_root() / "catalog")
    agents = _load_agent_specs(base)
    manages: dict[str, list[str]] = {aid: [] for aid in agents}

    for agent_id, spec in agents.items():
        reports_to = spec.get("org", {}).get("reports_to")
        if reports_to and reports_to in manages:
            manages[reports_to].append(agent_id)

    # Sort each list for determinism
    for aid in manages:
        manages[aid].sort()

    return manages


def _detect_cycles(agents: dict[str, dict[str, Any]]) -> list[str]:
    """Detect cycles in the reports_to hierarchy using DFS."""
    errors: list[str] = []
    visited: set[str] = set()
    in_stack: set[str] = set()

    def dfs(agent_id: str, path: list[str]) -> None:
        if agent_id in in_stack:
            cycle = path[path.index(agent_id) :]
            cycle.append(agent_id)
            errors.append(f"Cycle detected: {' → '.join(cycle)}")
            return
        if agent_id in visited:
            return
        visited.add(agent_id)
        in_stack.add(agent_id)
        path.append(agent_id)

        reports_to = agents.get(agent_id, {}).get("org", {}).get("reports_to")
        if reports_to and reports_to in agents:
            dfs(reports_to, path)

        path.pop()
        in_stack.discard(agent_id)

    for agent_id in agents:
        if agent_id not in visited:
            dfs(agent_id, [])

    return errors


def _detect_orphans(
    agents: dict[str, dict[str, Any]],
) -> list[str]:
    """Detect agents with no reports_to that aren't executive tier."""
    warnings: list[str] = []
    for agent_id, spec in agents.items():
        org = spec.get("org", {})
        reports_to = org.get("reports_to")
        org_level = org.get("org_level", "ic")
        if not reports_to and org_level not in ("executive", "utility"):
            warnings.append(
                f"Orphan agent '{agent_id}' has no reports_to and is not executive/utility tier"
            )
    return warnings


def _validate_escalation_chains(
    agents: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate escalation chains are acyclic and terminate at 'operator'."""
    errors: list[str] = []
    for agent_id, spec in agents.items():
        chain = spec.get("operation", {}).get("escalation", {}).get("chain", [])
        if not chain:
            continue
        # Check terminal
        if chain[-1] != "operator":
            errors.append(
                f"Agent '{agent_id}' escalation chain does not terminate at 'operator': {chain}"
            )
        # Check references exist (except "operator")
        for ref in chain:
            if ref != "operator" and ref not in agents:
                errors.append(
                    f"Agent '{agent_id}' escalation chain references unknown agent '{ref}'"
                )
        # Check for cycles in chain
        if len(chain) != len(set(chain)):
            errors.append(
                f"Agent '{agent_id}' escalation chain contains duplicates: {chain}"
            )
    return errors


def _validate_coordination_consistency(
    agents: dict[str, dict[str, Any]],
    manages: dict[str, list[str]],
) -> list[str]:
    """Validate coordination patterns are consistent with hierarchy."""
    warnings: list[str] = []
    for agent_id, spec in agents.items():
        coord = spec.get("operation", {}).get("coordination", {})
        pattern = coord.get("pattern", "standalone")

        if pattern == "orchestrator" and not manages.get(agent_id):
            warnings.append(
                f"Agent '{agent_id}' has coordination.pattern=orchestrator but manages no agents"
            )
        if pattern == "worker":
            # Worker should have a reports_to
            reports_to = spec.get("org", {}).get("reports_to")
            if not reports_to:
                warnings.append(
                    f"Agent '{agent_id}' has coordination.pattern=worker but no reports_to"
                )
    return warnings


def validate_agent_refs(
    spec: dict[str, Any],
    catalog_dir: Path | None = None,
) -> list[str]:
    """Per-agent validation at apply time.

    Checks reports_to, escalation chain, and handoff refs exist.
    Returns list of warning strings (not errors — allows forward references).
    """
    base = catalog_dir or (repo_root() / "catalog")
    agents = _load_agent_specs(base)
    warnings: list[str] = []

    org = spec.get("org", {})
    reports_to = org.get("reports_to")
    if reports_to and reports_to not in agents:
        warnings.append(f"reports_to '{reports_to}' not found in catalog (may be a forward reference)")

    chain = spec.get("operation", {}).get("escalation", {}).get("chain", [])
    for ref in chain:
        if ref != "operator" and ref not in agents:
            warnings.append(f"Escalation chain ref '{ref}' not found in catalog")

    coord = spec.get("operation", {}).get("coordination", {})
    for ref in coord.get("accepts_handoffs_from", []):
        if ref not in agents:
            warnings.append(f"accepts_handoffs_from ref '{ref}' not found in catalog")
    for ref in coord.get("produces_handoffs_for", []):
        if ref not in agents:
            warnings.append(f"produces_handoffs_for ref '{ref}' not found in catalog")

    return warnings


def audit_graph(catalog_dir: Path | None = None) -> GraphAuditResult:
    """Run full graph audit across all agent canonical specs.

    Detects cycles, orphans, invalid escalation chains,
    inconsistent coordination patterns.
    """
    base = catalog_dir or (repo_root() / "catalog")
    agents = _load_agent_specs(base)
    result = GraphAuditResult(agent_count=len(agents))

    # Derive manages
    manages = derive_manages(base)
    result.derived_manages = manages
    result.edge_count = sum(len(v) for v in manages.values())

    # Detect cycles
    cycle_errors = _detect_cycles(agents)
    result.errors.extend(cycle_errors)

    # Detect orphans
    orphan_warnings = _detect_orphans(agents)
    result.warnings.extend(orphan_warnings)

    # Validate escalation chains
    chain_errors = _validate_escalation_chains(agents)
    result.errors.extend(chain_errors)

    # Validate coordination consistency
    coord_warnings = _validate_coordination_consistency(agents, manages)
    result.warnings.extend(coord_warnings)

    result.valid = len(result.errors) == 0
    return result
