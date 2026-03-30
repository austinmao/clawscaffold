"""Generate and store Paperclip API keys for agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .cli_runner import KeyResult, generate_agent_key
from .hierarchy_reader import MergedAgent

# C-suite org levels that should provide the main workspace key
C_SUITE_LEVELS = {"executive", "director"}

KEY_STORAGE_DIR = Path.home() / ".openclaw" / "workspace" / "paperclip-agent-keys"
MAIN_KEY_PATH = Path.home() / ".openclaw" / "workspace" / "paperclip-claimed-api-key.json"


@dataclass
class KeyGenSummary:
    """Summary of key generation run."""

    generated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def generate_keys(
    agents: list[MergedAgent],
    company_id: str,
    force: bool = False,
    paperclip_dir: Path | None = None,
) -> KeyGenSummary:
    """Generate API keys for all agents via Paperclip CLI.

    Args:
        agents: List of merged agent specs.
        company_id: Paperclip company UUID.
        force: If True, regenerate keys even if key file exists.
        paperclip_dir: services/paperclip directory.

    Returns:
        KeyGenSummary with counts.
    """
    KEY_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    summary = KeyGenSummary()
    first_csuite_key: KeyResult | None = None

    for agent in agents:
        key_path = KEY_STORAGE_DIR / f"{agent.key}.json"

        # Skip if key exists and not forcing
        if key_path.is_file() and not force:
            summary.skipped += 1
            continue

        result = generate_agent_key(agent.key, company_id, paperclip_dir)

        if result.success:
            key_data = {
                "token": result.token,
                "agentId": result.agent_uuid,
                "companyId": result.company_uuid,
                "keyName": "local-cli",
            }
            key_path.write_text(json.dumps(key_data, indent=2))
            summary.generated += 1

            # Track first C-suite key for main workspace
            if first_csuite_key is None and agent.org_level in C_SUITE_LEVELS:
                first_csuite_key = result
        else:
            summary.failed += 1
            summary.errors.append(f"{agent.key}: {result.error}")

    # Copy first C-suite key to main workspace
    if first_csuite_key is not None:
        MAIN_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        main_data = {
            "token": first_csuite_key.token,
            "agentId": first_csuite_key.agent_uuid,
            "companyId": first_csuite_key.company_uuid,
            "keyName": "local-cli",
        }
        MAIN_KEY_PATH.write_text(json.dumps(main_data, indent=2))

    return summary
