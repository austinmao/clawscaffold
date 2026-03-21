"""Spec-managed path enforcement."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from clawscaffold.constants import MANAGED_REGISTRY_FILENAME
from clawscaffold.models import OutputManifest
from clawscaffold.paths import compiler_root
from clawscaffold.utils import now_iso, read_json, write_json


def registry_path(root: Path | None = None) -> Path:
    return compiler_root(root or Path.cwd()) / "ownership" / MANAGED_REGISTRY_FILENAME


def load_managed_registry(root: Path | None = None) -> dict:
    path = registry_path(root)
    if not path.exists():
        return {"paths": [], "targets": {}}
    data = read_json(path)
    data.setdefault("paths", [])
    data.setdefault("targets", {})
    return data


def is_spec_managed(path: str | Path, root: Path | None = None) -> bool:
    target = str(Path(path))
    registry = load_managed_registry(root)
    return target in registry.get("paths", [])


def guard_write(path: str | Path, command_prefix: str, root: Path | None = None) -> bool:
    if not is_spec_managed(path, root):
        return True
    allowed_prefixes = ("python3 scripts/scaffold.py", "uv run", "python scripts/scaffold.py")
    if any(command_prefix.startswith(prefix) for prefix in allowed_prefixes):
        return True
    raise PermissionError(f"Direct write blocked for compiler-managed path: {path}")


def generate_managed_registry(output_manifests: Iterable[OutputManifest], root: Path | None = None) -> Path:
    registry = load_managed_registry(root)
    targets = dict(registry.get("targets", {}))
    for manifest in output_manifests:
        key = f"{manifest.kind}:{manifest.target_id}"
        previous = targets.get(key, {})
        targets[key] = {
            "kind": manifest.kind,
            "id": manifest.target_id,
            "paths": sorted({entry.runtime_path for entry in manifest.files}),
            "first_managed_at": previous.get("first_managed_at", now_iso()),
            "updated_at": now_iso(),
        }
    paths = sorted({path for entry in targets.values() for path in entry.get("paths", [])})
    registry = {"paths": paths, "targets": targets}
    path = registry_path(root)
    write_json(path, registry)
    return path
