"""Paperclip export: generates YAML artifacts from governance records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawscaffold.governance import iter_governance_manifests
from clawscaffold.paths import default_tenant_name, repo_root, spec_roots
from clawscaffold.utils import ensure_dir, read_yaml, write_yaml


def export_agent_record(record: dict[str, Any]) -> dict[str, Any]:
    exported: dict[str, Any] = {
        "id": record["id"],
        "company": record.get("company", ""),
        "name": record.get("name", ""),
        "role": record.get("role", ""),
        "title": record.get("title", record.get("name", "")),
        "status": record.get("status", ""),
        "org": record.get("org", {}),
        "adapter": record.get("adapter", {}),
        "budget": record.get("budget", {}),
    }
    # Forward governance metadata when present (produced by governance_export)
    if record.get("governance"):
        exported["governance"] = record["governance"]
    if record.get("lifecycle"):
        exported["lifecycle"] = record["lifecycle"]
    if record.get("visibility"):
        exported["visibility"] = record["visibility"]
    return exported


def export_skill_record(record: dict[str, Any]) -> dict[str, Any]:
    """Transform a skill governance record to Paperclip export shape.

    Handles both the legacy nested ``governance`` dict format and the
    flattened format produced by ``governance_export()`` where governance
    fields (visibility, approval_tier, risk_tier, budget_tier,
    classification) live at the top level.
    """
    # If record has a nested governance dict, use it directly.
    # Otherwise, reconstruct from flattened top-level fields
    # (produced by governance_export()).
    gov = record.get("governance")
    if not gov or not isinstance(gov, dict):
        gov = {}
        for field in ("visibility", "approval_tier", "risk_tier",
                       "budget_tier", "classification", "routing"):
            if field in record:
                gov[field] = record[field]

    return {
        "id": record["id"],
        "name": record.get("name", ""),
        "title": record.get("title", record.get("name", "")),
        "status": record.get("status", ""),
        "org": record.get("org", {}),
        "governance": gov,
    }


def _resolve_company_data(exported_agents: list[dict[str, Any]], base: Path) -> dict[str, str]:
    companies = sorted({agent.get("company", "") for agent in exported_agents if agent.get("company")})
    if len(companies) > 1:
        raise ValueError(
            "export-paperclip requires records from a single company; found: " + ", ".join(companies)
        )
    if companies:
        return {"name": companies[0]}
    return {"name": default_tenant_name(base)}


def export_all(root: Path | None = None) -> dict[str, Any]:
    base = root or repo_root()
    gov_root = spec_roots(base).governance
    export_dir = gov_root / "exports" / "paperclip"
    ensure_dir(export_dir)

    # Read teams
    teams_path = gov_root / "teams.yaml"
    teams_data = read_yaml(teams_path) if teams_path.exists() else {"teams": []}

    # Collect exportable agents
    exported_agents: list[dict[str, Any]] = []
    for _path, record in iter_governance_manifests("agent", base):
        if not record.get("paperclip", {}).get("export", False):
            continue
        if record.get("deprecated", False):
            continue
        if record.get("status") != "active":
            continue
        exported_agents.append(export_agent_record(record))

    # Collect exportable skills
    exported_skills: list[dict[str, Any]] = []
    for _path, record in iter_governance_manifests("skill", base):
        if not record.get("paperclip", {}).get("export", False):
            continue
        if record.get("deprecated", False):
            continue
        if record.get("status") != "active":
            continue
        exported_skills.append(export_skill_record(record))

    company_data = _resolve_company_data(exported_agents, base)

    # Write exports
    write_yaml(export_dir / "company.yaml", company_data)
    write_yaml(export_dir / "agents.yaml", {"agents": exported_agents})
    if exported_skills:
        write_yaml(export_dir / "skills.yaml", {"skills": exported_skills})
    write_yaml(export_dir / "teams.yaml", teams_data)

    return {
        "export_dir": str(export_dir),
        "agents_exported": len(exported_agents),
        "skills_exported": len(exported_skills),
        "teams": len(teams_data.get("teams", [])),
    }
