"""Lobster adapter — translate stage manifests to .lobster YAML workflow files."""

from __future__ import annotations

from typing import Any

import yaml


SCRIPT_NAME_ALIASES = {
    "verify": "verify-campaign",
    "publish": "publish-campaign",
}


def generate_lobster(stages: list[dict[str, Any]], pipeline_name: str) -> str:
    """Generate a Lobster YAML workflow from a stage manifest."""
    steps = []

    for stage in stages:
        step: dict[str, Any] = {"id": stage["id"]}

        # Build command from stage definition
        agent = stage.get("agent", "unknown")
        command = stage.get("command")

        if command:
            # Use explicit command if provided
            step["command"] = command
        elif agent == "human-gate":
            prompt = stage.get("prompt", f"Pipeline {pipeline_name} is ready for review.")
            step["command"] = f'approve --prompt "{prompt}"'
            step["approval"] = "required"
        elif agent.startswith("script:"):
            script_name = agent.split(":", 1)[1]
            script_name = SCRIPT_NAME_ALIASES.get(script_name, script_name)
            step["command"] = f"scripts/lobster-{script_name}.sh ${{pipeline_id}}"
        elif agent != "unknown":
            task_desc = stage.get("task", f"Execute {stage['id']} stage for {pipeline_name}")
            # Escape single quotes in task description
            task_desc = task_desc.replace("'", "'\\''")
            step["command"] = f"scripts/lobster-spawn.sh {agent} '{task_desc}' 300"
        else:
            step["command"] = f"# TODO: implement {stage['id']}"

        # Add stdin wiring
        if "consumes" in stage and stage["consumes"]:
            step["stdin"] = stage["consumes"][0]

        # Add condition
        if "condition" in stage:
            step["condition"] = stage["condition"]

        if stage.get("approval"):
            step["approval"] = stage["approval"]
        elif stage.get("type") == "human-gate" or agent == "human-gate":
            step["approval"] = "required"

        steps.append(step)

    data = {"steps": steps}
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def parse_lobster_to_stages(lobster_path: str) -> list[dict[str, Any]]:
    """Parse a .lobster file and return stage definitions (for round-trip testing)."""
    with open(lobster_path) as f:
        data = yaml.safe_load(f)

    if not data or "steps" not in data:
        return []

    stages = []
    for step in data["steps"]:
        stage: dict[str, Any] = {"id": step["id"], "command": step.get("command", "")}
        if "stdin" in step:
            stage["consumes"] = [step["stdin"]]
        if "condition" in step:
            stage["condition"] = step["condition"]
        if step.get("approval"):
            stage["type"] = "human-gate"
        stages.append(stage)

    return stages
