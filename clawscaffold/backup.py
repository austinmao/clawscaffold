"""Backup and rollback system for scaffold adopt operations.

Creates timestamped backups of all workspace files before overwrite.
Supports rollback by run_id to restore original files.

Distinct from rollback.py which handles proposal-level snapshot/rollback
using compiler/runs/ directories.  This module uses compiler/backups/
with a {kind}s/{target_id}/{timestamp}/ hierarchy.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_base(base: Path | None) -> Path:
    return base if base is not None else _REPO_ROOT


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------

def create_backup(
    target_kind: str,
    target_id: str,
    run_id: str,
    files: list[Path],
    base: Path | None = None,
) -> Path:
    """Back up workspace files before scaffold adopt overwrites them.

    Creates ``compiler/backups/{kind}s/{target_id}/{ISO-timestamp}/`` and
    copies each file from *files* into the backup directory, preserving
    paths relative to *base*.  Files that do not exist are silently
    skipped.

    Returns the backup directory ``Path``.
    """
    base = _resolve_base(base)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backup_dir = base / "compiler" / "backups" / f"{target_kind}s" / target_id / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    backed_up: list[str] = []
    for file_path in files:
        abs_path = file_path if file_path.is_absolute() else base / file_path
        if not abs_path.exists():
            continue
        try:
            rel = abs_path.relative_to(base)
        except ValueError:
            # File lives outside the base tree -- use its name only.
            rel = Path(abs_path.name)
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(abs_path, dest)
        backed_up.append(str(rel))

    # Attempt to read original_schema_version from a spec file if present.
    original_schema_version: str | None = None
    spec_candidates = [
        base / "compiler" / "specs" / f"{target_id}.yaml",
        base / "specs" / f"{target_id}.yaml",
    ]
    for spec_path in spec_candidates:
        if spec_path.exists():
            try:
                with open(spec_path) as fh:
                    spec_data = yaml.safe_load(fh)
                if isinstance(spec_data, dict):
                    original_schema_version = spec_data.get("schema_version") or spec_data.get("version")
            except Exception:
                pass
            break

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp,
        "target_kind": target_kind,
        "target_id": target_id,
        "files": backed_up,
    }
    if original_schema_version is not None:
        manifest["original_schema_version"] = str(original_schema_version)

    with open(backup_dir / "manifest.yaml", "w") as fh:
        yaml.safe_dump(manifest, fh, default_flow_style=False, sort_keys=False)

    return backup_dir


# ---------------------------------------------------------------------------
# find_backup
# ---------------------------------------------------------------------------

def find_backup(run_id: str, base: Path | None = None) -> Path | None:
    """Locate backup directory for a given *run_id*.

    Scans all ``manifest.yaml`` files under ``compiler/backups/`` and
    returns the parent directory of the first manifest whose ``run_id``
    matches, or ``None`` if not found.
    """
    base = _resolve_base(base)
    backups_root = base / "compiler" / "backups"
    if not backups_root.exists():
        return None
    for manifest_path in sorted(backups_root.rglob("manifest.yaml")):
        try:
            with open(manifest_path) as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and data.get("run_id") == run_id:
                return manifest_path.parent
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------

def restore_backup(run_id: str, base: Path | None = None) -> dict[str, Any]:
    """Restore workspace files from a backup identified by *run_id*.

    Copies each backed-up file from the backup directory back to its
    original location under *base*.

    Returns the manifest ``dict``.

    Raises ``FileNotFoundError`` if no backup matches *run_id*.
    """
    base = _resolve_base(base)
    backup_dir = find_backup(run_id, base)
    if backup_dir is None:
        raise FileNotFoundError(f"No backup found for run_id: {run_id}")

    with open(backup_dir / "manifest.yaml") as fh:
        manifest: dict[str, Any] = yaml.safe_load(fh)

    for rel_str in manifest.get("files", []):
        src = backup_dir / rel_str
        dst = base / rel_str
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    return manifest


# ---------------------------------------------------------------------------
# list_backups
# ---------------------------------------------------------------------------

def list_backups(
    target_id: str,
    base: Path | None = None,
) -> list[tuple[str, str, Path]]:
    """List all backups for *target_id*.

    Returns a list of ``(timestamp, run_id, backup_path)`` tuples sorted
    by timestamp descending (most recent first).
    """
    base = _resolve_base(base)
    backups_root = base / "compiler" / "backups"
    if not backups_root.exists():
        return []

    results: list[tuple[str, str, Path]] = []
    for manifest_path in backups_root.rglob("manifest.yaml"):
        try:
            with open(manifest_path) as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and data.get("target_id") == target_id:
                results.append((
                    data.get("timestamp", ""),
                    data.get("run_id", ""),
                    manifest_path.parent,
                ))
        except Exception:
            continue

    results.sort(key=lambda t: t[0], reverse=True)
    return results
