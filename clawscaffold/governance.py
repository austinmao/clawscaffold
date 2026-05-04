"""Governance manifest helpers for the control-plane identity layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawscaffold.paths import repo_root, spec_roots
from clawscaffold.utils import ensure_dir, read_yaml, slug_to_title, write_yaml
from clawscaffold.validation import validate_dict


def governance_manifest_path(kind: str, target_id: str, root: Path | None = None) -> Path:
    base = root or repo_root()
    gov_root = spec_roots(base).governance
    parts = target_id.split("/")
    if kind == "agent":
        return gov_root / "agents" / "/".join(parts[:-1]) / f"{parts[-1]}.yaml"
    return gov_root / "skills" / "/".join(parts[:-1]) / f"{parts[-1]}.yaml"


def build_default_governance_record(
    kind: str,
    target_id: str,
    tenant: str,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # If a canonical spec is provided and has a governance block, delegate to
    # governance_export() which reads governance fields from the spec.
    if spec and spec.get("governance"):
        # Ensure the spec has the fields governance_export() expects.
        enriched = dict(spec)
        enriched.setdefault("id", target_id)
        enriched.setdefault("kind", kind)
        enriched.setdefault("tenant", tenant)
        return governance_export(enriched, kind)

    department = target_id.split("/", 1)[0]
    title = slug_to_title(target_id)

    if kind == "agent":
        return {
            "id": target_id,
            "type": "agent",
            "company": tenant,
            "name": title,
            "role": target_id.replace("/", "_").replace("-", "_"),
            "status": "active",
            "lifecycle": "active",
            "owner_team": department,
            "runtime_path": f"agents/{target_id}",
            "catalog_path": f"catalog/agents/{target_id}.yaml",
            "visibility": "internal",
            "approval_tier": "medium",
            "risk_tier": "medium",
            "budget_tier": "standard",
            "entrypoint": True,
            "aliases": [],
            "deprecated": False,
            "replacement": None,
            "org": {"team": department, "reports_to": None},
            "adapter": {
                "type": "openclaw",
                "config_ref": {"soul": f"agents/{target_id}/SOUL.md"},
            },
            "budget": {"tier": "standard", "monthly_usd_cap": 50},
        }

    return {
        "id": target_id,
        "type": "skill",
        "company": tenant,
        "name": title,
        "role": target_id.replace("/", "_").replace("-", "_"),
        "status": "active",
        "lifecycle": "active",
        "owner_team": department,
        "runtime_path": f"skills/{target_id}",
        "catalog_path": f"catalog/skills/{target_id}.yaml",
        "classification": "entrypoint",
        "visibility": "internal",
        "approval_tier": "low",
        "risk_tier": "low",
        "budget_tier": "economy",
        "entrypoint": True,
        "aliases": [],
        "deprecated": False,
        "replacement": None,
        "org": {"team": department, "reports_to": None},
        "adapter": {
            "type": "openclaw_skill",
            "config_ref": {"skill": f"skills/{target_id}/SKILL.md"},
        },
        "budget": {"tier": "economy", "monthly_usd_cap": 10},
        "routing": {"directly_invocable": True, "model_visible": True},
    }


def write_governance_manifest(record: dict[str, Any], root: Path | None = None) -> Path:
    base = root or repo_root()
    kind = record["type"]
    target_id = record["id"]
    schema_name = f"governance_{kind}.schema.json"
    validate_dict(record, schema_name, base)
    path = governance_manifest_path(kind, target_id, base)
    ensure_dir(path.parent)
    write_yaml(path, record)
    return path


def load_governance_manifest(path_or_id: str | Path, kind: str | None = None, root: Path | None = None) -> dict[str, Any]:
    base = root or repo_root()
    if isinstance(path_or_id, Path) or "/" in str(path_or_id) and str(path_or_id).endswith(".yaml"):
        return read_yaml(Path(path_or_id))
    if kind is None:
        raise ValueError("kind is required when loading by ID")
    path = governance_manifest_path(kind, str(path_or_id), base)
    return read_yaml(path)


def validate_governance_record(record: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    kind = record.get("type")
    if kind not in ("agent", "skill"):
        raise ValueError(f"Invalid governance record type: {kind}")

    schema_name = f"governance_{kind}.schema.json"
    validate_dict(record, schema_name, root)

    if kind == "skill":
        classification = record.get("classification")
        if classification == "subskill" and not record.get("parent_capability"):
            raise ValueError(f"Sub-skill {record['id']} requires parent_capability")

    if record.get("entrypoint") and record.get("status") == "active":
        for field in ("owner_team", "approval_tier", "risk_tier", "budget_tier"):
            if not record.get(field):
                raise ValueError(f"Active entrypoint {record['id']} requires {field}")

    return record


def governance_export(spec: dict[str, Any], kind: str | None = None) -> dict[str, Any]:
    """Derive a governance record from a canonical spec.

    The canonical spec's ``governance`` block is the source of truth.
    This function projects those fields into the governance record format
    expected by the existing governance system.
    """
    kind = kind or spec.get("kind", "agent")
    target_id = spec.get("id", "")
    tenant = spec.get("tenant", "ceremonia")
    department = spec.get("org", {}).get("department", target_id.split("/", 1)[0])
    title = spec.get("title") or slug_to_title(target_id)
    gov = spec.get("governance", {})
    provenance = spec.get("provenance", {})
    org = spec.get("org", {})

    lifecycle = provenance.get("lifecycle", "active")
    status = "active" if lifecycle in ("active", None) else lifecycle

    record: dict[str, Any] = {
        "id": target_id,
        "type": kind,
        "company": tenant,
        "name": title,
        "role": target_id.replace("/", "_"),
        "title": title,
        "status": status,
        "lifecycle": lifecycle,
        "owner_team": department,
        "runtime_path": f"{'agents' if kind == 'agent' else 'skills'}/{target_id}",
        "catalog_path": f"catalog/{kind}s/{target_id}.yaml",
        "visibility": gov.get("visibility", "internal"),
        "approval_tier": gov.get("approval_tier", "medium"),
        "risk_tier": gov.get("risk_tier", "low"),
        "budget_tier": gov.get("budget_tier", "standard"),
        "entrypoint": True,
        "aliases": [],
        "deprecated": status == "deprecated",
        "replacement": None,
        "org": {
            "team": department,
            "reports_to": org.get("reports_to"),
        },
        "adapter": {
            "type": "openclaw" if kind == "agent" else "openclaw_skill",
            "config_ref": {},
        },
        "budget": {
            "tier": gov.get("budget_tier", "standard"),
            "monthly_usd_cap": gov.get("monthly_usd_cap", 50 if kind == "agent" else 10),
        },
    }

    # Adapter config refs
    if kind == "agent":
        record["adapter"]["config_ref"] = {
            "soul": f"agents/{target_id}/SOUL.md",
            "heartbeat": f"agents/{target_id}/HEARTBEAT.md",
            "memory": f"agents/{target_id}/MEMORY.md",
        }
    else:
        record["adapter"]["config_ref"] = {
            "skill": f"skills/{target_id}/SKILL.md",
        }
        record["classification"] = gov.get("classification", "entrypoint")
        record["routing"] = gov.get("routing", {"directly_invocable": True, "model_visible": True})

    return record


def write_governance_from_spec(spec: dict[str, Any], base: Path | None = None) -> Path:
    """Write governance YAML derived from a canonical spec.

    Returns the written file path.
    """
    root = base or repo_root()
    kind = spec.get("kind", "agent")
    target_id = spec.get("id", "")
    record = governance_export(spec, kind)
    path = governance_manifest_path(kind, target_id, root)
    ensure_dir(path.parent)
    write_yaml(path, record)
    return path


def iter_governance_manifests(kind: str, root: Path | None = None):
    base = root or repo_root()
    gov_root = spec_roots(base).governance
    subdir = gov_root / ("agents" if kind == "agent" else "skills")
    if not subdir.exists():
        return
    for path in sorted(subdir.rglob("*.yaml")):
        yield path, read_yaml(path)
