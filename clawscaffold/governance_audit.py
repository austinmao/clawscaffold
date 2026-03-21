"""Generic governance audit log — append-only YAML log of governance API calls.

Backend-agnostic: records HTTP method, endpoint, payload, and response without
referencing any specific governance system.  Daily-rotated files at
``<log_dir>/YYYY-MM-DD.yaml``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _log_path(log_dir: Path, date: datetime | None = None) -> Path:
    """Return the audit log file path for the given date (defaults to today UTC)."""
    if date is None:
        date = datetime.now(timezone.utc)
    return log_dir / f"{date.strftime('%Y-%m-%d')}.yaml"


def append_entry(entry: dict[str, Any], *, log_dir: str | Path) -> None:
    """Append a single governance audit entry to the daily log file.

    Creates the log directory and file if they do not exist.  Each entry gets
    a ``timestamp`` field set to the current UTC time.

    Args:
        entry: Mapping with action, target_id, target_kind, method, endpoint,
               payload, response_status, response_id, success, error.
        log_dir: Directory where daily YAML log files are stored.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    path = _log_path(log_dir, now)

    record: dict[str, Any] = {"timestamp": now.isoformat()}
    record.update(entry)

    # Read existing entries (if any) and append
    existing: list[dict[str, Any]] = []
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw)
        if isinstance(loaded, list):
            existing = loaded

    existing.append(record)
    path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False), encoding="utf-8")


def read_entries(
    *,
    log_dir: str | Path,
    date: datetime | None = None,
    action_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Read governance audit entries from the daily log file.

    Args:
        log_dir: Directory containing daily YAML log files.
        date: Which day's log to read (defaults to today UTC).
        action_filter: If provided, only return entries with this action value.

    Returns:
        List of audit entry dicts, or empty list if the file does not exist.
    """
    log_dir = Path(log_dir)
    path = _log_path(log_dir, date)

    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, list):
        return []

    entries: list[dict[str, Any]] = loaded

    if action_filter is not None:
        entries = [e for e in entries if e.get("action") == action_filter]

    return entries
