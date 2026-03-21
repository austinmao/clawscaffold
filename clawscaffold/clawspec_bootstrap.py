"""Helpers for making a local ``clawspec`` checkout importable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from clawscaffold.paths import repo_root


def candidate_package_roots(root: Path | None = None) -> list[Path]:
    workspace_root = (root or repo_root()).resolve()
    candidates: list[Path] = []

    explicit_repo = os.environ.get("CLAWSPEC_REPO")
    if explicit_repo:
        repo = Path(explicit_repo).expanduser().resolve()
        candidates.extend([repo / "src", repo])

    sibling_repo = workspace_root.parent / "clawspec"
    candidates.extend([sibling_repo / "src", sibling_repo])
    return candidates


def bootstrap_clawspec(root: Path | None = None, *, marker: str = "__init__.py") -> Path | None:
    try:
        import clawspec  # noqa: F401

        return None
    except ModuleNotFoundError:
        pass

    for package_root in candidate_package_roots(root):
        package_file = package_root / "clawspec" / marker
        if not package_file.exists():
            continue
        package_root_str = str(package_root)
        if package_root_str not in sys.path:
            sys.path.insert(0, package_root_str)
        return package_root

    return None
