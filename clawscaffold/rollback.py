"""Snapshot creation and rollback helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from clawscaffold.config_apply import apply_config_ops
from clawscaffold.utils import read_json, write_json


def create_snapshot(run_dir: Path, file_paths: list[Path]) -> list[dict[str, str | bool]]:
    snapshot_root = run_dir / "snapshot"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for file_path in file_paths:
        snapshot_path = snapshot_root / file_path.relative_to(file_path.anchor if file_path.is_absolute() else Path("."))
        if file_path.exists():
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, snapshot_path)
            manifest.append({"path": str(file_path), "snapshot": str(snapshot_path), "existed": True})
        else:
            manifest.append({"path": str(file_path), "snapshot": "", "existed": False})
    write_json(run_dir / "snapshot-manifest.json", manifest)
    return manifest


def rollback_run(run_id: str, root: Path | None = None) -> Path:
    repo = root or Path.cwd()
    run_dir = repo / "compiler" / "runs" / run_id
    rollback_info = read_json(run_dir / "rollback.json")
    restored = []
    for entry in rollback_info.get("files", []):
        runtime_path = Path(entry["path"])
        snapshot = entry.get("snapshot")
        if entry.get("existed") and snapshot:
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot, runtime_path)
        elif runtime_path.exists():
            runtime_path.unlink()
        restored.append(str(runtime_path))
    reverse_ops = []
    for op in reversed(rollback_info.get("config_ops", [])):
        previous = op.get("previous_value")
        if previous is None:
            reverse_ops.append({"action": "unset", "key": op["key"]})
        else:
            reverse_ops.append({"action": "set", "key": op["key"], "value": previous})
    apply_config_ops(reverse_ops)
    result_path = run_dir / "rollback-result.json"
    write_json(result_path, {"run_id": run_id, "restored": restored, "config_reverted": len(reverse_ops)})
    return result_path
