"""Documentation section generation."""

from __future__ import annotations

from pathlib import Path

from clawscaffold.models import ResolvedManifest
from clawscaffold.utils import sha256_prefix, today_iso, upsert_marked_section, write_text

AGENT_CATALOG_MARKER_ID = "governance-agent-catalog"
SKILL_CATALOG_MARKER_ID = "governance-skill-catalog"


def _doc_section(marker_id: str, content: str) -> str:
    checksum = sha256_prefix(content)
    generated = today_iso()
    return (
        f"<!-- oc:section id=\"{marker_id}\" source=\"compiler/generated\" checksum=\"{checksum}\" generated=\"{generated}\" -->\n"
        f"{content.rstrip()}\n"
        f"<!-- /oc:section id=\"{marker_id}\" -->"
    )


def generate_registry_section(resolved: ResolvedManifest) -> str:
    kind = resolved.kind
    content = (
        f"## Compiler Managed: `{resolved.target_id}`\n\n"
        f"- Kind: `{kind}`\n"
        f"- Tenant: `{resolved.target.tenant}`\n"
        f"- Profiles: {', '.join(resolved.target.policy.get('profiles', [])) or 'none'}\n"
    )
    return _doc_section(f"registry-{resolved.target_id.replace('/', '-')}", content)


def generate_claude_md_section(resolved: ResolvedManifest) -> str:
    content = (
        f"- {resolved.target_id}: compiler-managed {resolved.kind} "
        f"with tenant `{resolved.target.tenant}` and cognition "
        f"`{resolved.resolved.get('resolved_cognition', {}).get('model', 'unresolved')}`"
    )
    return _doc_section(f"claude-{resolved.target_id.replace('/', '-')}", content)


def write_generated_doc_artifacts(resolved: ResolvedManifest, root: Path | None = None) -> tuple[Path, Path]:
    repo = root or Path.cwd()
    output_dir = repo / "compiler" / "generated" / "docs"
    registry_path = output_dir / f"{resolved.target_id.replace('/', '--')}-registry.md"
    claude_path = output_dir / f"{resolved.target_id.replace('/', '--')}-claude.md"
    write_text(registry_path, generate_registry_section(resolved))
    write_text(claude_path, generate_claude_md_section(resolved))
    return registry_path, claude_path


def _render_agent_catalog_table(root: Path | None = None) -> list[str]:
    from clawscaffold.governance import iter_governance_manifests

    base = root or Path.cwd()
    lines = ["| ID | Name | Team | Status | Visibility | Export |", "|---|---|---|---|---|---|"]

    for _path, record in iter_governance_manifests("agent", base):
        rid = record.get("id", "")
        name = record.get("name", "")
        team = record.get("owner_team", "")
        status = record.get("status", "")
        vis = record.get("visibility", "")
        export = "yes" if record.get("paperclip", {}).get("export") else "no"
        lines.append(f"| `{rid}` | {name} | {team} | {status} | {vis} | {export} |")

    return lines


def _render_skill_catalog_table(root: Path | None = None) -> list[str]:
    from clawscaffold.governance import iter_governance_manifests

    base = root or Path.cwd()
    lines = ["| ID | Name | Classification | Team | Parent | Status |", "|---|---|---|---|---|---|"]

    for _path, record in iter_governance_manifests("skill", base):
        rid = record.get("id", "")
        name = record.get("name", "")
        classification = record.get("classification", "")
        team = record.get("owner_team", "")
        parent = record.get("parent_capability", "-")
        status = record.get("status", "")
        lines.append(f"| `{rid}` | {name} | {classification} | {team} | {parent} | {status} |")

    return lines


def render_agent_catalog_doc(root: Path | None = None) -> str:
    lines = ["# Deployed OpenClaw Agents", "", *_render_agent_catalog_table(root), ""]
    return "\n".join(lines)


def render_skill_catalog_doc(root: Path | None = None) -> str:
    lines = ["# Deployed OpenClaw Skills", "", *_render_skill_catalog_table(root), ""]
    return "\n".join(lines)


def _managed_catalog_section(marker_id: str, title: str, table_lines: list[str]) -> str:
    content = "\n".join(
        [
            f"## {title}",
            "",
            "This section is generated from governance manifests. Do not edit inside this block.",
            "",
            *table_lines,
            "",
        ]
    )
    return _doc_section(marker_id, content)


def _ensure_doc_stub(document_path: Path, title: str) -> None:
    if document_path.exists():
        return
    write_text(document_path, f"# {title}\n\n")


def regenerate_governance_docs(root: Path | None = None) -> dict[str, Path]:
    base = root or Path.cwd()
    paths: dict[str, Path] = {}

    agents_doc = base / "docs" / "technical" / "agents.md"
    agents_doc.parent.mkdir(parents=True, exist_ok=True)
    _ensure_doc_stub(agents_doc, "Agent Catalog")
    apply_generated_section(
        agents_doc,
        AGENT_CATALOG_MARKER_ID,
        _managed_catalog_section(
            AGENT_CATALOG_MARKER_ID,
            "Generated Governance Catalog",
            _render_agent_catalog_table(base),
        ),
    )
    paths["agents"] = agents_doc

    skills_doc = base / "docs" / "technical" / "skills.md"
    _ensure_doc_stub(skills_doc, "Skill Catalog")
    apply_generated_section(
        skills_doc,
        SKILL_CATALOG_MARKER_ID,
        _managed_catalog_section(
            SKILL_CATALOG_MARKER_ID,
            "Generated Governance Catalog",
            _render_skill_catalog_table(base),
        ),
    )
    paths["skills"] = skills_doc

    return paths


def apply_generated_section(document_path: Path, marker_id: str, content: str) -> None:
    existing = document_path.read_text(encoding="utf-8") if document_path.exists() else ""
    updated = upsert_marked_section(existing, marker_id, content)
    write_text(document_path, updated)
