"""Drift classification for managed paths."""

from __future__ import annotations

from pathlib import Path

from clawscaffold.enforcement import load_managed_registry


def classify_drift(path: str | Path, managed: bool) -> str:
    path_obj = Path(path)
    if managed and not path_obj.exists():
        return "critical"
    if managed:
        return "error"
    if not path_obj.exists():
        return "warning"
    return "informational"


def scan_all_managed_paths(root: Path | None = None) -> list[dict[str, str]]:
    registry = load_managed_registry(root)
    report = []
    for path in registry.get("paths", []):
        report.append({"path": path, "severity": classify_drift(path, managed=True)})
    return report
