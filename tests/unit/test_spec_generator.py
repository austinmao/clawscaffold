"""Tests for spec generator."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clawscaffold.scaffold.spec_generator import (
    generate_spec,
    infer_agent_from_command,
    parse_lobster_file,
    step_to_stage,
)


def test_infer_agent_from_spawn():
    cmd = 'exec --shell "scripts/lobster-spawn.sh agents-marketing-copywriter \'Write copy\' 300"'
    assert infer_agent_from_command(cmd) == "agents-marketing-copywriter"


def test_infer_agent_from_script():
    cmd = 'exec --shell "scripts/lobster-verify-campaign.sh have-a-good-trip-v2 webinar"'
    assert infer_agent_from_command(cmd) == "script:verify-campaign"


def test_infer_agent_from_approval():
    cmd = 'approve --prompt "Ready for review"'
    assert infer_agent_from_command(cmd) == "human-gate"


def test_infer_agent_unknown():
    cmd = "exec --shell \"echo hello\""
    assert infer_agent_from_command(cmd) == "script:unknown"


def test_step_to_stage_basic():
    step = {"id": "copy", "command": 'exec --shell "scripts/lobster-spawn.sh agents-marketing-copywriter \'task\' 300"'}
    stage = step_to_stage(step)
    assert stage["id"] == "copy"
    assert stage["agent"] == "agents-marketing-copywriter"


def test_step_to_stage_preserves_explicit_command_for_round_trip():
    step = {
        "id": "init",
        "command": "python3 scripts/lobster-campaign-run.py init --pipeline-id '${pipeline_id}'",
    }
    stage = step_to_stage(step)
    assert stage["command"] == step["command"]


def test_step_to_stage_with_stdin():
    step = {"id": "html", "command": "exec --stdin json --shell \"cmd\"", "stdin": "$copy.stdout"}
    stage = step_to_stage(step)
    assert stage["consumes"] == ["$copy.stdout"]


def test_step_to_stage_with_approval():
    step = {"id": "approval", "command": "approve --prompt \"ok?\"", "approval": "required"}
    stage = step_to_stage(step)
    assert stage["type"] == "human-gate"
    assert stage["agent"] == "human-gate"
    assert stage["approval"] == "required"


def test_step_to_stage_with_condition():
    step = {"id": "deploy", "command": "exec --shell \"deploy.sh\"", "condition": "$approval.approved"}
    stage = step_to_stage(step)
    assert stage["condition"] == "$approval.approved"


def test_step_to_stage_preserves_explicit_stage_metadata():
    stage = step_to_stage(
        {
            "id": "approval",
            "agent": "human-gate",
            "type": "human-gate",
            "verdict": "required",
            "parallel": True,
        }
    )
    assert stage == {
        "id": "approval",
        "agent": "human-gate",
        "type": "human-gate",
        "verdict": "required",
        "parallel": True,
    }


def test_parse_lobster_file(tmp_path):
    lobster = tmp_path / "test.lobster"
    lobster.write_text(yaml.dump({
        "steps": [
            {"id": "step1", "command": "exec --shell \"echo 1\""},
            {"id": "step2", "command": "exec --shell \"echo 2\""},
        ]
    }))
    steps = parse_lobster_file(lobster)
    assert len(steps) == 2
    assert steps[0]["id"] == "step1"


def test_parse_lobster_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_lobster_file("/nonexistent.lobster")


def test_parse_lobster_file_invalid(tmp_path):
    lobster = tmp_path / "bad.lobster"
    lobster.write_text("not: valid\nlobster: file\n")
    with pytest.raises(ValueError, match="must contain a 'steps' array"):
        parse_lobster_file(lobster)


def test_parse_lobster_file_empty_steps(tmp_path):
    lobster = tmp_path / "empty.lobster"
    lobster.write_text(yaml.dump({"steps": []}))
    with pytest.raises(ValueError, match="at least one step"):
        parse_lobster_file(lobster)


def test_generate_spec():
    steps = [
        {"id": "copy", "command": 'exec --shell "scripts/lobster-spawn.sh agents-marketing-copywriter \'task\' 300"'},
        {"id": "approval", "command": 'approve --prompt "ok?"', "approval": "required"},
    ]
    spec_text = generate_spec("test-pipeline", steps, "workflows/test.lobster")

    assert spec_text.startswith("---\n")
    assert "kind: pipeline" in spec_text
    assert "name: test-pipeline" in spec_text

    # Parse the frontmatter to verify it's valid YAML
    lines = spec_text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break
    fm_text = "\n".join(lines[1:end_idx])
    data = yaml.safe_load(fm_text)
    assert len(data["stages"]) == 2
    assert data["stages"][0]["agent"] == "agents-marketing-copywriter"


def test_generate_spec_with_unknown_agent():
    steps = [
        {"id": "mystery", "command": 'exec --shell "some-random-script.sh"'},
    ]
    spec_text = generate_spec("test", steps, "test.lobster")
    assert "unknown" in spec_text


def test_generate_spec_preserves_canonical_stage_definitions():
    stages = [
        {"id": "verify", "agent": "script:verify", "type": "verification"},
        {"id": "brand-gate", "agent": "unknown", "verdict": "required"},
        {"id": "approval", "agent": "human-gate", "type": "human-gate"},
    ]

    spec_text = generate_spec("test", stages, "workflows/test.lobster")

    lines = spec_text.split("\n")
    end_idx = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    data = yaml.safe_load("\n".join(lines[1:end_idx]))

    assert data["stages"] == stages
