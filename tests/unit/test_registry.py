"""Tests for pipeline registry."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from clawscaffold.scaffold.registry import (
    add_target,
    get_target,
    list_targets,
    update_field,
    update_runtime_paths,
    update_status,
)


@pytest.fixture
def tmp_registry(tmp_path):
    return tmp_path / "registry.yaml"


def test_add_target_creates_file(tmp_registry):
    entry = add_target(
        name="newsletter",
        kind="pipeline",
        spec_path="targets/pipeline/newsletter/spec.md",
        runtime_path="workflows/campaign-newsletter.lobster",
        registry_path=tmp_registry,
    )
    assert entry["name"] == "newsletter"
    assert entry["kind"] == "pipeline"
    assert entry["status"] == "adopted"
    assert entry["runtime_paths"] == ["workflows/campaign-newsletter.lobster"]
    assert tmp_registry.exists()


def test_add_target_duplicate_rejected(tmp_registry):
    add_target(
        name="newsletter",
        kind="pipeline",
        spec_path="t.md",
        runtime_path="w.lobster",
        registry_path=tmp_registry,
    )
    with pytest.raises(ValueError, match="already exists"):
        add_target(
            name="newsletter",
            kind="pipeline",
            spec_path="t.md",
            runtime_path="w.lobster",
            registry_path=tmp_registry,
        )


def test_add_target_invalid_kind(tmp_registry):
    with pytest.raises(ValueError, match="Invalid kind"):
        add_target(
            name="x",
            kind="invalid",
            spec_path="t.md",
            runtime_path="w.lobster",
            registry_path=tmp_registry,
        )


def test_get_target(tmp_registry):
    add_target(
        name="newsletter",
        kind="pipeline",
        spec_path="t.md",
        runtime_path="w.lobster",
        registry_path=tmp_registry,
    )
    result = get_target("newsletter", "pipeline", tmp_registry)
    assert result is not None
    assert result["name"] == "newsletter"


def test_get_target_not_found(tmp_registry):
    result = get_target("missing", "pipeline", tmp_registry)
    assert result is None


def test_list_targets(tmp_registry):
    add_target(name="a", kind="pipeline", spec_path="a.md", runtime_path="a.lobster", registry_path=tmp_registry)
    add_target(name="b", kind="skill", spec_path="b.md", runtime_path="b.md", registry_path=tmp_registry)

    all_targets = list_targets(registry_path=tmp_registry)
    assert len(all_targets) == 2

    pipelines = list_targets(kind="pipeline", registry_path=tmp_registry)
    assert len(pipelines) == 1
    assert pipelines[0]["name"] == "a"


def test_update_status(tmp_registry):
    add_target(name="x", kind="pipeline", spec_path="x.md", runtime_path="x.lobster", registry_path=tmp_registry)
    result = update_status("x", "pipeline", "managed", tmp_registry)
    assert result["status"] == "managed"


def test_update_status_invalid(tmp_registry):
    add_target(name="x", kind="pipeline", spec_path="x.md", runtime_path="x.lobster", registry_path=tmp_registry)
    with pytest.raises(ValueError, match="Invalid status"):
        update_status("x", "pipeline", "invalid", tmp_registry)


def test_update_field(tmp_registry):
    add_target(name="x", kind="pipeline", spec_path="x.md", runtime_path="x.lobster", registry_path=tmp_registry)
    result = update_field("x", "pipeline", "last_audit", "2026-03-19", tmp_registry)
    assert result["last_audit"] == "2026-03-19"


def test_update_runtime_paths(tmp_registry):
    add_target(name="x", kind="pipeline", spec_path="x.md", runtime_path="x.lobster", registry_path=tmp_registry)
    result = update_runtime_paths("x", "pipeline", ["x.lobster", "x.prose", "x.lobster"], tmp_registry)
    assert result["runtime_paths"] == ["x.lobster", "x.prose"]
