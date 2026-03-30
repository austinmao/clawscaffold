"""Detect Paperclip availability and discover company ID."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PaperclipEnvironment:
    """Result of Paperclip environment detection."""

    available: bool
    api_url: str | None
    company_id: str | None
    paperclip_dir: Path | None


def _find_paperclip_dir(repo_root: Path) -> Path | None:
    """Return services/paperclip directory if it exists, else None."""
    candidate = repo_root / "services" / "paperclip"
    return candidate if candidate.is_dir() else None


def _check_cli_available(paperclip_dir: Path | None) -> bool:
    """Return True if `pnpm paperclipai --version` exits with code 0."""
    try:
        result = subprocess.run(
            ["pnpm", "paperclipai", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(paperclip_dir) if paperclip_dir else None,
            shell=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _discover_company_id(paperclip_dir: Path | None) -> str | None:
    """Try to discover the first company ID via the Paperclip CLI.

    Returns the ID string on success, or None if discovery fails.
    """
    try:
        result = subprocess.run(
            ["pnpm", "paperclipai", "company", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(paperclip_dir) if paperclip_dir else None,
            shell=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if isinstance(data, list) and data:
                company_id = data[0].get("id")
                return str(company_id) if company_id is not None else None
            if isinstance(data, dict):
                companies = data.get("companies", data.get("data", []))
                if companies:
                    company_id = companies[0].get("id")
                    return str(company_id) if company_id is not None else None
    except (
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        pass
    return None


def detect_paperclip(repo_root: Path) -> PaperclipEnvironment:
    """Detect Paperclip availability and resolve configuration.

    Detection order:
    1. PAPERCLIP_API_URL env var — if set, Paperclip is available.
    2. ``pnpm paperclipai --version`` succeeding in services/paperclip.
    3. Neither works → available=False.

    Company ID resolution:
    1. PAPERCLIP_COMPANY_ID env var.
    2. Auto-discover via ``pnpm paperclipai company list --json`` (only when available).
    3. Falls back to None.

    Args:
        repo_root: Repository root directory.

    Returns:
        PaperclipEnvironment with availability status and resolved config.
    """
    paperclip_dir = _find_paperclip_dir(repo_root)

    # --- Availability ---
    env_url = os.environ.get("PAPERCLIP_API_URL") or None  # None if empty/unset
    if env_url:
        available = True
        api_url: str | None = env_url
    elif _check_cli_available(paperclip_dir):
        available = True
        api_url = None
    else:
        return PaperclipEnvironment(
            available=False,
            api_url=None,
            company_id=None,
            paperclip_dir=paperclip_dir,
        )

    # --- Company ID ---
    env_company = os.environ.get("PAPERCLIP_COMPANY_ID") or None
    if env_company:
        company_id: str | None = env_company
    else:
        company_id = _discover_company_id(paperclip_dir)

    return PaperclipEnvironment(
        available=available,
        api_url=api_url,
        company_id=company_id,
        paperclip_dir=paperclip_dir,
    )
