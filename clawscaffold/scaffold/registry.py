"""Pipeline registry — CRUD for targets/registry.yaml."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

VALID_KINDS = ("agent", "skill", "pipeline")
VALID_STATUSES = ("adopted", "managed", "promoted")

DEFAULT_REGISTRY_PATH = Path("targets/registry.yaml")


def _normalize_runtime_paths(primary_path: str, runtime_paths: list[str] | None = None) -> list[str]:
    paths = [primary_path]
    if runtime_paths:
        paths.extend(runtime_paths)

    seen: set[str] = set()
    normalized: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return normalized


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"targets": []}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if "targets" not in data:
        data["targets"] = []
    return data


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def add_target(
    name: str,
    kind: str,
    spec_path: str,
    runtime_path: str,
    runtime_paths: list[str] | None = None,
    engine: str = "lobster",
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        raise ValueError(f"Invalid kind: {kind}. Must be one of {VALID_KINDS}")

    data = _load(registry_path)

    for t in data["targets"]:
        if t["name"] == name and t["kind"] == kind:
            raise ValueError(f"Target already exists: {kind}/{name}")

    entry = {
        "name": name,
        "kind": kind,
        "status": "adopted",
        "spec_path": spec_path,
        "runtime_path": runtime_path,
        "runtime_paths": _normalize_runtime_paths(runtime_path, runtime_paths),
        "engine": engine,
        "adopted_at": datetime.now(timezone.utc).isoformat(),
        "last_audit": None,
        "last_apply": None,
    }
    data["targets"].append(entry)
    _save(registry_path, data)
    return entry


def get_target(
    name: str,
    kind: str = "pipeline",
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any] | None:
    data = _load(registry_path)
    for t in data["targets"]:
        if t["name"] == name and t.get("kind") == kind:
            return t
    return None


def list_targets(
    kind: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> list[dict[str, Any]]:
    data = _load(registry_path)
    if kind:
        return [t for t in data["targets"] if t.get("kind") == kind]
    return data["targets"]


def update_status(
    name: str,
    kind: str,
    status: str,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

    data = _load(registry_path)
    for t in data["targets"]:
        if t["name"] == name and t.get("kind") == kind:
            t["status"] = status
            _save(registry_path, data)
            return t
    raise ValueError(f"Target not found: {kind}/{name}")


def update_field(
    name: str,
    kind: str,
    field: str,
    value: Any,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    data = _load(registry_path)
    for t in data["targets"]:
        if t["name"] == name and t.get("kind") == kind:
            t[field] = value
            _save(registry_path, data)
            return t
    raise ValueError(f"Target not found: {kind}/{name}")


def update_runtime_paths(
    name: str,
    kind: str,
    runtime_paths: list[str],
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    return update_field(
        name,
        kind,
        "runtime_paths",
        _normalize_runtime_paths(runtime_paths[0], runtime_paths[1:]) if runtime_paths else [],
        registry_path,
    )
