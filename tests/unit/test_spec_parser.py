"""Tests for spec parser."""

from __future__ import annotations

import pytest

from clawscaffold.scaffold.spec_parser import (
    get_certification,
    get_stages,
    parse_spec_text,
)


VALID_SPEC = """---
kind: pipeline
name: newsletter
version: "1.0.0"
runtime: openclaw
engine: lobster
stages:
  - id: copy
    agent: agents-marketing-copywriter
  - id: email-html
    agent: agents-marketing-email-engineer
    consumes: ["$copy.output"]
certification:
  required:
    - clawspec-contracts
  optional:
    - brand-gate-pass-rate
---

# Newsletter Pipeline

Some documentation here.
"""


def test_parse_valid_spec():
    data = parse_spec_text(VALID_SPEC)
    assert data["kind"] == "pipeline"
    assert data["name"] == "newsletter"
    assert data["engine"] == "lobster"
    assert len(data["stages"]) == 2
    assert data["stages"][0]["id"] == "copy"


def test_parse_missing_frontmatter():
    with pytest.raises(ValueError, match="must start with ---"):
        parse_spec_text("no frontmatter here")


def test_parse_unclosed_frontmatter():
    with pytest.raises(ValueError, match="missing closing ---"):
        parse_spec_text("---\nkind: pipeline\nname: test\n")


def test_parse_missing_kind():
    with pytest.raises(ValueError, match="missing required field: kind"):
        parse_spec_text("---\nname: test\n---\n")


def test_parse_missing_name():
    with pytest.raises(ValueError, match="missing required field: name"):
        parse_spec_text("---\nkind: pipeline\n---\n")


def test_get_stages():
    data = parse_spec_text(VALID_SPEC)
    stages = get_stages(data)
    assert len(stages) == 2
    assert stages[1]["agent"] == "agents-marketing-email-engineer"


def test_get_certification():
    data = parse_spec_text(VALID_SPEC)
    cert = get_certification(data)
    assert "clawspec-contracts" in cert["required"]
    assert "brand-gate-pass-rate" in cert["optional"]


def test_body_extracted():
    data = parse_spec_text(VALID_SPEC)
    assert "Newsletter Pipeline" in data["_body"]
    assert "Some documentation here" in data["_body"]
