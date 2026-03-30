"""Generate .paperclip.yaml from merged agent specs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .hierarchy_reader import MergedAgent
from .soul_condenser import condense_soul_file


def generate_paperclip_yaml(
    agents: list[MergedAgent],
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Build .paperclip.yaml dict from merged agent specs.

    Args:
        agents: List of merged agent specs with hierarchy overrides applied.

    Returns:
        Dict ready for YAML serialization as .paperclip.yaml.
    """
    gateway_url = os.environ.get("OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18789")
    auth_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

    agents_dict: dict[str, Any] = {}
    sidebar_agents: list[str] = []

    for agent in agents:
        agent_entry: dict[str, Any] = {
            "role": agent.role,
            "capabilities": agent.description or None,
            "adapter": {
                "type": "openclaw_gateway",
                "config": {
                    "url": gateway_url,
                    "sessionKeyStrategy": "run",
                },
            },
        }

        if auth_token:
            agent_entry["adapter"]["config"]["authToken"] = auth_token

        # Set agentId so the gateway routes to the agent's own workspace
        # (requires PR #1206 session key fix in Paperclip adapter)
        agent_entry["adapter"]["config"]["agentId"] = agent.key

        # Set promptTemplate with condensed SOUL.md identity.
        # promptTemplate is rendered as the system prompt BEFORE the wake
        # procedure, so the LLM knows its role and instructions.
        # This is the Paperclip-recommended mechanism (see issue #206).
        if repo_root:
            soul_path = repo_root / "agents" / agent.id / "SOUL.md"
            condensed = condense_soul_file(soul_path)
            if condensed:
                agent_entry["adapter"]["config"]["promptTemplate"] = condensed

        if agent.emoji:
            agent_entry["icon"] = agent.emoji

        if agent.reports_to_key:
            agent_entry["reportsTo"] = agent.reports_to_key

        if agent.budget_monthly_cents:
            agent_entry["budgetMonthlyCents"] = agent.budget_monthly_cents

        # Heartbeat / lifecycle config
        if agent.heartbeat_enabled or agent.lifecycle_bridge != "not_enrolled":
            agent_entry["runtime"] = {
                "heartbeat": {
                    "enabled": agent.heartbeat_enabled,
                    "intervalSec": 60,
                    "wakeOnDemand": True,
                },
            }

        if agent.timeout_sec != 60:
            agent_entry.setdefault("adapter", {}).setdefault("config", {})["timeoutSec"] = (
                agent.timeout_sec
            )

        agents_dict[agent.key] = agent_entry
        sidebar_agents.append(agent.key)

    return {
        "schema": "paperclip/v1",
        "agents": agents_dict,
        "sidebar": {"agents": sidebar_agents},
    }
