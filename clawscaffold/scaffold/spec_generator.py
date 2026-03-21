"""Generate pipeline specs from existing .lobster workflow files."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def parse_lobster_file(path: Path | str) -> list[dict[str, Any]]:
    """Parse a .lobster YAML workflow file and extract step definitions."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Lobster file not found: {path}")

    text = path.read_text()
    data = yaml.safe_load(text)

    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError(f"Invalid Lobster file: must contain a 'steps' array")

    steps = data["steps"]
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError("Lobster file must have at least one step")

    return steps


def infer_agent_from_command(command: str) -> str:
    """Extract agent ID from a lobster-spawn.sh command string."""
    # Pattern: lobster-spawn.sh <agent-id> '<task>'
    match = re.search(r"lobster-spawn\.sh\s+(\S+)", command)
    if match:
        return match.group(1)

    # Pattern: lobster-verify-campaign.sh or lobster-record-create.sh
    match = re.search(r"lobster-(\w[\w-]+)\.sh", command)
    if match:
        return f"script:{match.group(1)}"

    # Approval gate
    if "approve" in command.lower():
        return "human-gate"

    # Generic shell command
    if "exec --shell" in command:
        return "script:unknown"

    return "unknown"


def step_to_stage(step: dict[str, Any]) -> dict[str, Any]:
    """Convert a Lobster step to a pipeline stage definition."""
    stage: dict[str, Any] = {"id": step["id"]}

    command = step.get("command", "")
    if "command" in step:
        stage["command"] = command

    if step.get("approval"):
        stage["agent"] = step.get("agent") or "human-gate"
    else:
        stage["agent"] = step.get("agent") or infer_agent_from_command(command)

    if "consumes" in step:
        stage["consumes"] = step["consumes"]
    elif "stdin" in step:
        stage["consumes"] = [step["stdin"]]

    if "condition" in step:
        stage["condition"] = step["condition"]

    if "approval" in step:
        stage["approval"] = step["approval"]

    if "type" in step:
        stage["type"] = step["type"]
    elif step.get("approval"):
        stage["type"] = "human-gate"

    if "verdict" in step:
        stage["verdict"] = step["verdict"]
    elif "verdict" in command.lower() or "brand-gate-check" in command:
        stage["verdict"] = "required"

    # Detect verification scripts when no explicit type is present.
    if "type" not in stage and "verify-campaign" in command:
        stage["type"] = "verification"

    if "parallel" in step:
        stage["parallel"] = step["parallel"]

    return stage


def generate_spec(
    name: str,
    steps: list[dict[str, Any]],
    source_path: str,
    engine: str = "lobster",
) -> str:
    """Generate a pipeline spec (Markdown + YAML frontmatter) from Lobster steps."""
    stages = [step_to_stage(s) for s in steps]

    frontmatter = {
        "kind": "pipeline",
        "name": name,
        "version": "1.0.0",
        "runtime": "openclaw",
        "engine": engine,
        "status": "adopted",
        "source": source_path,
        "adopted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "stages": stages,
        "certification": {
            "required": [],
            "optional": [],
        },
    }

    yaml_text = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

    body_lines = [
        f"# Pipeline: {name}",
        "",
        f"Adopted from `{source_path}` on {frontmatter['adopted_at']}.",
        "",
        "## Stages",
        "",
    ]

    for stage in stages:
        agent_label = stage["agent"]
        stage_type = stage.get("type", "agent-task")
        body_lines.append(f"### {stage['id']}")
        body_lines.append(f"- Agent: `{agent_label}`")
        body_lines.append(f"- Type: {stage_type}")
        if "consumes" in stage:
            body_lines.append(f"- Consumes: {', '.join(stage['consumes'])}")
        if "condition" in stage:
            body_lines.append(f"- Condition: `{stage['condition']}`")
        if stage.get("verdict"):
            body_lines.append(f"- Verdict: {stage['verdict']}")
        body_lines.append("")

    return f"---\n{yaml_text}---\n\n" + "\n".join(body_lines)


def write_spec(name: str, source_path: str, output_dir: Path | None = None) -> Path:
    """Parse a .lobster file and write a pipeline spec."""
    steps = parse_lobster_file(source_path)
    spec_text = generate_spec(name, steps, source_path)

    if output_dir is None:
        output_dir = Path(f"targets/pipeline/{name}")

    output_dir.mkdir(parents=True, exist_ok=True)
    spec_path = output_dir / "spec.md"
    spec_path.write_text(spec_text)

    return spec_path
