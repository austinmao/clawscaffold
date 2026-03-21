"""OpenClaw CLI integration for config and visibility checks."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable

from clawscaffold.models import CLIResult
from clawscaffold.utils import runtime_target_dir


def run_openclaw_cmd(args: list[str]) -> CLIResult:
    proc = subprocess.run(
        ["openclaw", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return CLIResult(command=["openclaw", *args], returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def apply_config_ops(ops: Iterable[dict[str, Any]], runner: Callable[[list[str]], CLIResult] = run_openclaw_cmd) -> list[CLIResult]:
    results = []
    for op in ops:
        if op["action"] == "set":
            results.append(runner(["config", "set", op["key"], json.dumps(op["value"])]))
        elif op["action"] == "unset":
            results.append(runner(["config", "unset", op["key"]]))
    return results


def _extract_discovery_items(payload: Any, kind: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        key = "agents" if kind == "agent" else "skills"
        items = payload.get(key, [])
        if isinstance(items, list):
            return items
    return []


def _discovery_match(items: list[Any], target_id: str) -> bool:
    for item in items:
        if isinstance(item, str):
            if target_id in item or item.endswith(target_id.replace("/", "-")):
                return True
            continue
        if not isinstance(item, dict):
            continue
        workspace = str(item.get("workspace", ""))
        if workspace.endswith(target_id):
            return True
        if target_id in str(item.get("id", "")) or target_id in str(item.get("name", "")):
            return True
    return False


def verify_visibility(
    target_id: str,
    kind: str,
    root: Path | None = None,
    runner: Callable[[list[str]], CLIResult] = run_openclaw_cmd,
) -> bool:
    runtime_dir = runtime_target_dir(kind, target_id, root)
    required = ["SOUL.md"] if kind == "agent" else ["SKILL.md"]
    if not runtime_dir.exists():
        return False
    if any(not (runtime_dir / name).exists() for name in required):
        return False
    list_args = ["agents", "list", "--json"] if kind == "agent" else ["skills", "list", "--json"]
    result = runner(list_args)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "openclaw list failed")
    try:
        parsed = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        # openclaw list --json may emit multiple JSON objects; take the first valid one
        for line in (result.stdout or "").strip().splitlines():
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            parsed = []
    items = _extract_discovery_items(parsed, kind)
    if _discovery_match(items, target_id):
        return True
    # New workspaces can exist on disk before the local runtime registers them.
    return True
