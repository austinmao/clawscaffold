"""Path helpers for clawscaffold-managed directories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpecRoots:
    catalog: Path
    profiles: Path
    tenants: Path
    governance: Path


def repo_root(start: Path | None = None) -> Path:
    """Find the project root by walking up to a .clawscaffold marker or catalog/ dir.

    Resolution order:
    1. CLAWSCAFFOLD_ROOT env var (explicit override for CI)
    2. Walk up from start (or CWD) looking for .clawscaffold marker
    3. Walk up looking for pyproject.toml + catalog/ (OpenClaw repo pattern)
    4. Raise RuntimeError with clear remediation instructions
    """
    env_root = os.environ.get("CLAWSCAFFOLD_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.exists():
            return p

    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".clawscaffold").exists():
            return parent
        if (parent / "pyproject.toml").exists() and (parent / "catalog").exists():
            return parent

    raise RuntimeError(
        "Cannot find project root. Either:\n"
        "  - Run 'clawscaffold init' in your project directory\n"
        "  - Set CLAWSCAFFOLD_ROOT environment variable\n"
        "  - Create a .clawscaffold marker file in your project root"
    )


def compiler_root(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "compiler"


def generated_root(root: Path | None = None) -> Path:
    return compiler_root(root) / "generated"


def spec_roots(root: Path | None = None) -> SpecRoots:
    base = root or repo_root()
    return SpecRoots(
        catalog=base / "catalog",
        profiles=base / "profiles",
        tenants=base / "tenants",
        governance=base / "governance",
    )


def default_tenant_name(root: Path | None = None) -> str:
    tenants_root = spec_roots(root).tenants
    tenant_specs = sorted(tenants_root.glob("*/tenant.yaml"))
    if tenant_specs:
        return tenant_specs[0].parent.name
    if tenants_root.exists():
        tenant_dirs = sorted(path for path in tenants_root.iterdir() if path.is_dir())
        if tenant_dirs:
            return tenant_dirs[0].name
    return "default"
