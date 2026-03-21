"""Runtime-to-canonical adoption helpers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from clawscaffold.constants import ADOPTION_REGISTRY_FILENAME
from clawscaffold.interview import build_default_agent_spec, build_default_skill_spec
from clawscaffold.models import MigrationReport, SectionContent, TargetSpec
from clawscaffold.paths import compiler_root, default_tenant_name, repo_root
from clawscaffold.section_parser import infer_policy_hints, parse_sections, parse_skill_sections
from clawscaffold.utils import (
    canonical_target_path,
    deep_merge,
    now_iso,
    read_json,
    read_yaml,
    slug_to_title,
    write_json,
    write_yaml,
)


def _repo_path(path: str | Path, root: Path | None = None) -> Path:
    repo = root or repo_root()
    candidate = Path(path)
    return candidate if candidate.is_absolute() else repo / candidate


def _repo_rel(path: str | Path, root: Path | None = None) -> str:
    repo = (root or repo_root()).resolve()
    return str(_repo_path(path, root).resolve().relative_to(repo))


def infer_target_from_runtime_path(runtime_path: str | Path, root: Path | None = None) -> tuple[str, str]:
    path = _repo_path(runtime_path, root)
    parts = path.parts
    if "agents" in parts:
        index = parts.index("agents")
        target_id = "/".join(parts[index + 1 : -1])
        return "agent", target_id
    if "skills" in parts:
        index = parts.index("skills")
        target_id = "/".join(parts[index + 1 : -1])
        return "skill", target_id
    raise ValueError(f"Cannot infer target kind from path: {runtime_path}")


def _extract_headings(text: str) -> list[str]:
    return [section.heading for section in parse_sections(text)]


def _sections_payload(sections: list[SectionContent]) -> dict[str, dict[str, Any]]:
    return {section.id: section.to_dict() for section in sections}


def _merge_policy_hints(draft: dict[str, Any], hints: dict[str, Any]) -> None:
    memory_mode = hints.get("memory", {}).get("retrieval_mode")
    if memory_mode:
        draft.setdefault("policy", {}).setdefault("memory", {})["retrieval_mode"] = memory_mode
    cognition = hints.get("cognition", {}).get("complexity")
    if cognition:
        draft.setdefault("policy", {}).setdefault("cognition", {})["complexity"] = cognition
    skill_refs = hints.get("skills", [])
    if skill_refs:
        existing = list(draft.setdefault("operation", {}).get("integrations", []))
        for ref in skill_refs:
            if ref not in existing:
                existing.append(ref)
        draft["operation"]["integrations"] = existing
    channels = hints.get("channels", [])
    if channels and draft["kind"] == "agent":
        existing_types = {channel.get("type") for channel in draft.setdefault("operation", {}).get("channels", [])}
        for channel in channels:
            if channel not in existing_types:
                draft["operation"]["channels"].append(
                    {
                        "type": channel,
                        "audience": "operator",
                        "mode": "both",
                        "approval_posture": "confirm" if hints.get("approvals") else "auto",
                    }
                )
    if hints.get("approvals"):
        draft.setdefault("operation", {}).setdefault("approvals", {})["default"] = hints["approvals"][0]


def _non_default_policy_updates(kind: str, target_id: str, existing: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    defaults = build_default_agent_spec(target_id, existing.get("tenant")) if kind == "agent" else build_default_skill_spec(target_id, existing.get("tenant"))
    updates: dict[str, Any] = {"policy": {}, "operation": {}}

    default_memory = defaults.get("policy", {}).get("memory", {}).get("retrieval_mode")
    current_memory = existing.get("policy", {}).get("memory", {}).get("retrieval_mode")
    extracted_memory = extracted.get("policy", {}).get("memory", {}).get("retrieval_mode")
    if extracted_memory and extracted_memory != default_memory and current_memory == default_memory:
        updates["policy"].setdefault("memory", {})["retrieval_mode"] = extracted_memory

    default_complexity = defaults.get("policy", {}).get("cognition", {}).get("complexity")
    current_complexity = existing.get("policy", {}).get("cognition", {}).get("complexity")
    extracted_complexity = extracted.get("policy", {}).get("cognition", {}).get("complexity")
    if extracted_complexity and extracted_complexity != default_complexity and current_complexity == default_complexity:
        updates["policy"].setdefault("cognition", {})["complexity"] = extracted_complexity

    extracted_integrations = extracted.get("operation", {}).get("integrations", [])
    current_integrations = existing.get("operation", {}).get("integrations", [])
    if extracted_integrations and not current_integrations:
        updates["operation"]["integrations"] = extracted_integrations

    extracted_approvals = extracted.get("operation", {}).get("approvals", {})
    current_approvals = existing.get("operation", {}).get("approvals", {})
    if extracted_approvals and not current_approvals:
        updates["operation"]["approvals"] = extracted_approvals

    if not updates["policy"]:
        updates.pop("policy")
    if not updates["operation"]:
        updates.pop("operation")
    return updates


def adoption_registry_path(root: Path | None = None) -> Path:
    return compiler_root(root or Path.cwd()) / "ownership" / ADOPTION_REGISTRY_FILENAME


def load_adoption_registry(root: Path | None = None) -> dict[str, Any]:
    path = adoption_registry_path(root)
    if not path.exists():
        return {"version": 1, "updated_at": None, "targets": {}, "runtime_sources": {}}
    data = read_json(path)
    data.setdefault("version", 1)
    data.setdefault("updated_at", None)
    data.setdefault("targets", {})
    data.setdefault("runtime_sources", {})
    return data


def _registry_key(kind: str, target_id: str) -> str:
    return f"{kind}:{target_id}"


def _iter_runtime_sources(root: Path) -> list[Path]:
    paths = list((root / "agents").rglob("SOUL.md")) + list((root / "skills").rglob("SKILL.md"))
    return sorted(path for path in paths if path.is_file())


def _inventory_status(kind: str, target_id: str, root: Path) -> tuple[str, str]:
    canonical_path = canonical_target_path(kind, target_id, root)
    if not canonical_path.exists():
        return "untracked", "missing"
    lifecycle = str(read_yaml(canonical_path).get("provenance", {}).get("lifecycle", "draft"))
    if lifecycle == "active":
        return "managed", lifecycle
    return "draft", lifecycle


def sync_adoption_inventory(root: Path | None = None) -> Path:
    repo = root or repo_root()
    timestamp = now_iso()
    previous = load_adoption_registry(repo)
    previous_targets = previous.get("targets", {})
    registry = {"version": 1, "updated_at": timestamp, "targets": {}, "runtime_sources": {}}

    for runtime_path in _iter_runtime_sources(repo):
        kind, target_id = infer_target_from_runtime_path(runtime_path, repo)
        key = _registry_key(kind, target_id)
        prior = previous_targets.get(key, {})
        status, lifecycle = _inventory_status(kind, target_id, repo)
        entry = {
            "kind": kind,
            "id": target_id,
            "runtime_source_path": _repo_rel(runtime_path, repo),
            "canonical_path": _repo_rel(canonical_target_path(kind, target_id, repo), repo),
            "status": status,
            "lifecycle": lifecycle,
            "first_registered_at": prior.get("first_registered_at", timestamp),
            "updated_at": timestamp,
        }
        for field in ("last_run_id", "last_action", "last_adopted_at", "promoted_at"):
            if field in prior:
                entry[field] = prior[field]
        registry["targets"][key] = entry
        registry["runtime_sources"][entry["runtime_source_path"]] = key

    path = adoption_registry_path(repo)
    write_json(path, registry)
    return path


def find_adoption_entry(kind: str, target_id: str, root: Path | None = None) -> dict[str, Any] | None:
    registry = load_adoption_registry(root)
    return registry.get("targets", {}).get(_registry_key(kind, target_id))


def find_adoption_entry_for_runtime(runtime_path: str | Path, root: Path | None = None) -> dict[str, Any] | None:
    registry = load_adoption_registry(root)
    runtime_key = _repo_rel(runtime_path, root)
    target_key = registry.get("runtime_sources", {}).get(runtime_key)
    if not target_key:
        return None
    return registry.get("targets", {}).get(target_key)


def record_adoption_event(
    kind: str,
    target_id: str,
    runtime_path: str | Path,
    action: str,
    root: Path | None = None,
    run_id: str | None = None,
) -> Path:
    repo = root or repo_root()
    path = sync_adoption_inventory(repo)
    registry = read_json(path)
    key = _registry_key(kind, target_id)
    entry = registry.get("targets", {}).get(key)
    if entry is None:
        entry = {
            "kind": kind,
            "id": target_id,
            "runtime_source_path": _repo_rel(runtime_path, repo),
            "canonical_path": _repo_rel(canonical_target_path(kind, target_id, repo), repo),
            "status": "untracked",
            "lifecycle": "missing",
            "first_registered_at": now_iso(),
            "updated_at": now_iso(),
        }
    entry["runtime_source_path"] = entry.get("runtime_source_path") or _repo_rel(runtime_path, repo)
    entry["updated_at"] = now_iso()
    entry["last_action"] = action
    if run_id:
        entry["last_run_id"] = run_id
    if action == "adopt":
        entry["last_adopted_at"] = now_iso()
    if action == "promote":
        entry["promoted_at"] = now_iso()
    registry.setdefault("targets", {})[key] = entry
    registry.setdefault("runtime_sources", {})[entry["runtime_source_path"]] = key
    registry["updated_at"] = now_iso()
    write_json(path, registry)
    return path


def generate_draft_spec(runtime_path: str | Path, root: Path | None = None) -> dict[str, Any]:
    path = _repo_path(runtime_path, root)
    kind, target_id = infer_target_from_runtime_path(path, root)
    tenant = default_tenant_name(root)
    text = path.read_text(encoding="utf-8")
    if kind == "agent":
        draft = build_default_agent_spec(target_id, tenant)
        sections = parse_sections(text)
        hints = infer_policy_hints(sections)
        draft["title"] = slug_to_title(target_id)
        draft["description"] = f"Adopted from runtime file `{path.name}`."
        draft["agent"]["workspace_files"] = sorted(
            file.name for file in path.parent.iterdir() if file.is_file() and file.suffix == ".md"
        )
        draft["agent"]["heartbeat"]["enabled"] = (path.parent / "HEARTBEAT.md").exists()
        if sections:
            draft["agent"]["soul_voice_section"] = sections[0].heading
            draft["agent"]["sections"] = _sections_payload(sections)
        _merge_policy_hints(draft, hints)
    else:
        frontmatter, sections = parse_skill_sections(text)
        hints = infer_policy_hints(sections)
        draft = build_default_skill_spec(target_id, tenant)
        draft["title"] = frontmatter.get("name", slug_to_title(target_id))
        draft["description"] = frontmatter.get("description", f"Adopted skill for `{target_id}`.")
        version = frontmatter.get("version")
        if isinstance(version, str) and version:
            draft["skill"]["version"] = version
        draft["identity"]["emoji"] = frontmatter.get("metadata", {}).get("openclaw", {}).get("emoji", ":wrench:")
        permissions = frontmatter.get("permissions")
        if isinstance(permissions, dict):
            draft["skill"]["permissions"] = permissions
        triggers = frontmatter.get("triggers")
        if isinstance(triggers, list):
            draft["skill"]["triggers"] = triggers
        requires = frontmatter.get("metadata", {}).get("openclaw", {}).get("requires")
        if isinstance(requires, dict):
            draft["skill"]["requires"] = requires
        if sections:
            draft["skill"]["usage_section"] = sections[0].content.strip().splitlines()[0] if sections[0].content.strip() else ""
            draft["skill"]["sections"] = _sections_payload(sections)
        _merge_policy_hints(draft, hints)
    draft["provenance"]["updated_at"] = now_iso()
    return draft


def build_backfilled_spec(
    target_id: str,
    kind: str,
    *,
    root: Path | None = None,
    existing_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_path = _repo_path(
        f"{'agents' if kind == 'agent' else 'skills'}/{target_id}/{'SOUL.md' if kind == 'agent' else 'SKILL.md'}",
        root,
    )
    extracted = generate_draft_spec(runtime_path, root)
    if existing_spec is None:
        existing_path = canonical_target_path(kind, target_id, root)
        existing_spec = read_yaml(existing_path) if existing_path.exists() else extracted

    merged = deepcopy(existing_spec)
    merged["kind"] = existing_spec.get("kind", extracted["kind"])
    merged["id"] = existing_spec.get("id", extracted["id"])
    merged["tenant"] = existing_spec.get("tenant", extracted["tenant"])
    merged["provenance"] = dict(existing_spec.get("provenance", {}))
    merged["provenance"]["updated_at"] = now_iso()

    if kind == "agent":
        merged.setdefault("agent", {})
        merged["agent"]["sections"] = extracted.get("agent", {}).get("sections", {})
        if not merged["agent"].get("soul_voice_section"):
            merged["agent"]["soul_voice_section"] = extracted.get("agent", {}).get("soul_voice_section", "")
    else:
        merged.setdefault("skill", {})
        for key in ("version", "permissions", "requires", "triggers", "usage_section", "sections"):
            if key in extracted.get("skill", {}):
                merged["skill"][key] = extracted["skill"][key]
        if extracted.get("operation", {}).get("triggers"):
            merged.setdefault("operation", {})
            merged["operation"]["triggers"] = extracted["operation"]["triggers"]
        if extracted.get("identity", {}).get("emoji") and not merged.get("identity", {}).get("emoji"):
            merged.setdefault("identity", {})
            merged["identity"]["emoji"] = extracted["identity"]["emoji"]

    policy_updates = _non_default_policy_updates(kind, target_id, existing_spec, extracted)
    if policy_updates:
        merged = deep_merge(merged, policy_updates)
    return merged


def generate_migration_report(draft: dict[str, Any], runtime_path: str | Path) -> MigrationReport:
    path = Path(runtime_path)
    text = path.read_text(encoding="utf-8")
    kind, target_id = infer_target_from_runtime_path(path)
    if kind == "agent":
        sections = parse_sections(text)
    else:
        _frontmatter, sections = parse_skill_sections(text)
    headings = [section.heading for section in sections]
    hints = infer_policy_hints(sections)
    report = MigrationReport(
        runtime_path=str(path),
        inferred_kind=kind,
        inferred_id=target_id,
        extracted_fields={
            "title": draft["title"],
            "profiles": draft["policy"]["profiles"],
            "headings": headings,
            "sections": [section.to_dict() for section in sections],
            "policy_hints": hints,
            "section_sources": {section.id: section.source for section in sections},
        },
        unmapped_sections=[heading for heading in headings if heading not in {"Who I Am", "Core Principles", "Usage"}],
        profile_matches=draft["policy"]["profiles"],
        recommendations=["Review adopted policy defaults before promote."],
    )
    return report


def promote_to_managed(draft_path: str | Path, root: Path | None = None, run_id: str | None = None) -> Path:
    path = _repo_path(draft_path, root)
    spec = TargetSpec.from_dict(__import__("yaml").safe_load(path.read_text(encoding="utf-8")))
    spec.provenance["lifecycle"] = "active"
    spec.provenance["updated_at"] = now_iso()
    write_yaml(path, spec.to_dict())
    runtime_path = _repo_path(f"{'agents' if spec.kind == 'agent' else 'skills'}/{spec.id}/{'SOUL.md' if spec.kind == 'agent' else 'SKILL.md'}", root)
    record_adoption_event(spec.kind, spec.id, runtime_path, action="promote", root=root, run_id=run_id)
    return path
