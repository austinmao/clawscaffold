"""Organization audit: validates alignment across runtime, catalog, and governance layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawscaffold.governance import iter_governance_manifests, validate_governance_record
from clawscaffold.paths import repo_root, spec_roots
from clawscaffold.utils import read_yaml
from clawscaffold.validation import SchemaValidationError


def _scan_runtime(kind: str, root: Path) -> set[str]:
    if kind == "agent":
        base = root / "agents"
        marker = "SOUL.md"
    else:
        base = root / "skills"
        marker = "SKILL.md"
    ids: set[str] = set()
    if not base.exists():
        return ids
    for marker_file in sorted(base.rglob(marker)):
        rel = marker_file.parent.relative_to(base)
        ids.add(str(rel))
    return ids


def _scan_catalog(kind: str, root: Path) -> set[str]:
    catalog_dir = spec_roots(root).catalog / (f"{kind}s")
    ids: set[str] = set()
    if not catalog_dir.exists():
        return ids
    for yaml_path in sorted(catalog_dir.rglob("*.yaml")):
        rel = yaml_path.relative_to(catalog_dir)
        ids.add(str(rel).replace(".yaml", ""))
    return ids


def _scan_governance(kind: str, root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for _path, record in iter_governance_manifests(kind, root):
        records[record.get("id", "")] = record
    return records


def run_organization_audit(root: Path | None = None) -> dict[str, Any]:
    base = root or repo_root()
    errors: list[str] = []
    warnings: list[str] = []

    for kind in ("agent", "skill"):
        runtime_ids = _scan_runtime(kind, base)
        catalog_ids = _scan_catalog(kind, base)
        gov_records = _scan_governance(kind, base)
        gov_ids = set(gov_records.keys())

        # Coverage: active runtime items should have governance records
        for rid in sorted(runtime_ids):
            if rid not in gov_ids:
                warnings.append(f"Runtime {kind} '{rid}' has no governance record")

        # Coverage: governance records should have catalog records
        for gid in sorted(gov_ids):
            record = gov_records[gid]
            if record.get("status") == "active" and gid not in catalog_ids:
                warnings.append(f"Active governance {kind} '{gid}' has no catalog record")

        # Validate each governance record
        for gid, record in sorted(gov_records.items()):
            try:
                validate_governance_record(record, base)
            except (ValueError, SchemaValidationError) as exc:
                errors.append(f"Governance {kind} '{gid}': {exc}")

        # Duplicate alias detection
        seen_aliases: dict[str, str] = {}
        for gid, record in gov_records.items():
            for alias in record.get("aliases", []):
                if alias in seen_aliases:
                    errors.append(
                        f"Duplicate alias '{alias}' claimed by both '{gid}' and '{seen_aliases[alias]}'"
                    )
                elif alias in gov_ids:
                    errors.append(
                        f"Alias '{alias}' of '{gid}' collides with canonical ID of another record"
                    )
                else:
                    seen_aliases[alias] = gid

        # Conflict detection: governance lifecycle vs runtime presence
        for gid, record in sorted(gov_records.items()):
            lifecycle = record.get("lifecycle", record.get("status"))
            has_runtime = gid in runtime_ids
            if lifecycle in ("active",) and not has_runtime:
                warnings.append(
                    f"Governance {kind} '{gid}' is '{lifecycle}' but has no runtime files"
                )
            if lifecycle in ("retired",) and has_runtime:
                warnings.append(
                    f"Governance {kind} '{gid}' is 'retired' but still has runtime files"
                )

    return {
        "errors": errors,
        "warnings": warnings,
        "passed": len(errors) == 0,
    }
