"""Tests for scaffold CLI helpers."""

from __future__ import annotations

from argparse import Namespace

from clawscaffold.scaffold.cli import cmd_create
from clawscaffold.scaffold.spec_parser import parse_spec_text


def test_cmd_create_preserves_canonical_stage_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = cmd_create(
        Namespace(
            name="demo-pipeline",
            kind="pipeline",
            registry_path=tmp_path / "registry.yaml",
        )
    )

    assert result == 0

    spec_path = tmp_path / "targets" / "pipeline" / "demo-pipeline" / "spec.md"
    assert spec_path.exists()

    spec = parse_spec_text(spec_path.read_text())
    stages = {stage["id"]: stage for stage in spec["stages"]}

    assert stages["generate"]["type"] == "content-generation"
    assert stages["verify"]["agent"] == "script:verify"
    assert stages["verify"]["type"] == "verification"
    assert stages["brand-gate"]["verdict"] == "required"
    assert stages["approval"]["agent"] == "human-gate"
    assert stages["approval"]["type"] == "human-gate"
    assert stages["publish"]["type"] == "publication"
    assert stages["post-audit"]["type"] == "certification"
