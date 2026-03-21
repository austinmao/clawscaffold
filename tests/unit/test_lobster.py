"""Tests for the Lobster adapter."""

from __future__ import annotations

import yaml

from clawscaffold.scaffold.adapters.lobster import generate_lobster


def test_generate_lobster_uses_runnable_shell_commands_for_script_and_agent_stages():
    workflow = generate_lobster(
        [
            {"id": "verify", "agent": "script:verify"},
            {
                "id": "copy",
                "agent": "agents-marketing-copywriter",
                "task": "Write the launch copy",
            },
        ],
        "demo-pipeline",
    )

    steps = yaml.safe_load(workflow)["steps"]

    assert steps[0]["command"] == "scripts/lobster-verify-campaign.sh ${pipeline_id}"
    assert steps[1]["command"] == (
        "scripts/lobster-spawn.sh agents-marketing-copywriter "
        "'Write the launch copy' 300"
    )


def test_generate_lobster_preserves_explicit_commands():
    workflow = generate_lobster(
        [
            {
                "id": "init",
                "agent": "unknown",
                "command": "python3 scripts/lobster-campaign-run.py init --pipeline-id '${pipeline_id}'",
            }
        ],
        "demo-pipeline",
    )

    steps = yaml.safe_load(workflow)["steps"]

    assert steps[0]["command"] == (
        "python3 scripts/lobster-campaign-run.py init --pipeline-id '${pipeline_id}'"
    )
