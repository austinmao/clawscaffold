"""Register agents with the OpenClaw gateway for per-agent workspace routing."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .hierarchy_reader import MergedAgent


@dataclass
class GatewayRegistration:
    """Result of gateway agent registration."""

    registered: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def register_agents_with_gateway(
    agents: list[MergedAgent],
    repo_root: Path,
) -> GatewayRegistration:
    """Register each agent with the OpenClaw gateway.

    Each agent gets its own entry in the gateway's agents.list with
    a workspace pointing to ``agents/<domain>/<name>/`` (where its
    SOUL.md lives). This allows the gateway to load per-agent
    instructions when Paperclip wakes that agent.

    Uses ``openclaw agents add <key> --workspace <path>``.

    Args:
        agents: List of merged agent specs.
        repo_root: Repository root directory.

    Returns:
        GatewayRegistration with counts.
    """
    result = GatewayRegistration()

    for agent in agents:
        workspace_path = repo_root / "agents" / agent.id
        if not workspace_path.is_dir():
            result.skipped += 1
            continue

        # Check if SOUL.md exists in workspace
        if not (workspace_path / "SOUL.md").is_file():
            result.skipped += 1
            continue

        try:
            proc = subprocess.run(
                [
                    "openclaw",
                    "agents",
                    "add",
                    agent.key,
                    "--workspace",
                    str(workspace_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                result.registered += 1
            else:
                # May already be registered — not an error
                stderr = proc.stderr.strip()
                if "already" in stderr.lower() or "exists" in stderr.lower():
                    result.skipped += 1
                else:
                    result.failed += 1
                    result.errors.append(f"{agent.key}: exit {proc.returncode} — {stderr[:100]}")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            result.failed += 1
            result.errors.append(f"{agent.key}: {exc}")

    return result
