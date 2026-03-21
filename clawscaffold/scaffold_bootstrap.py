"""Helpers for making a local ``clawscaffold`` checkout importable."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from clawscaffold.paths import repo_root

logger = logging.getLogger(__name__)


def candidate_package_roots(root: Path | None = None) -> list[Path]:
    workspace_root = (root or repo_root()).resolve()
    candidates: list[Path] = []

    explicit_repo = os.environ.get("CLAWSCAFFOLD_REPO")
    if explicit_repo:
        repo = Path(explicit_repo).expanduser().resolve()
        candidates.extend([repo / "src", repo])

    sibling_repo = workspace_root.parent / "clawscaffold"
    candidates.extend([sibling_repo / "src", sibling_repo])
    return candidates


def bootstrap_clawscaffold(root: Path | None = None, *, marker: str = "__init__.py") -> Path | None:
    """Try to import standalone clawscaffold, fall back to sibling repo or vendored copy.

    Returns the resolved package root Path if a sibling repo was found, or None
    if the standalone package was already importable.
    """
    try:
        import clawscaffold  # noqa: F401
        return None  # standalone package available
    except ModuleNotFoundError:
        pass

    for package_root in candidate_package_roots(root):
        package_file = package_root / "clawscaffold" / marker
        if not package_file.exists():
            continue
        package_root_str = str(package_root)
        if package_root_str not in sys.path:
            sys.path.insert(0, package_root_str)
        logger.info("Using clawscaffold from: %s", package_root)
        return package_root

    logger.warning("clawscaffold not installed — using vendored compiler/engine/ modules")
    return None
