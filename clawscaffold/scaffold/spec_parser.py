"""Parse pipeline spec files (Markdown + YAML frontmatter)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def parse_spec(path: Path | str) -> dict[str, Any]:
    """Parse a pipeline spec file and return the frontmatter as a dict.

    Spec files use Markdown + YAML frontmatter (--- delimited),
    matching the SKILL.md convention.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Spec file not found: {path}")

    text = path.read_text()
    return parse_spec_text(text)


def parse_spec_text(text: str) -> dict[str, Any]:
    """Parse spec text and return frontmatter dict."""
    lines = text.strip().split("\n")

    if not lines or lines[0].strip() != "---":
        raise ValueError("Spec file must start with --- (YAML frontmatter)")

    # Find closing ---
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("Spec file missing closing --- for YAML frontmatter")

    frontmatter_text = "\n".join(lines[1:end_idx])
    data = yaml.safe_load(frontmatter_text)

    if not isinstance(data, dict):
        raise ValueError("YAML frontmatter must be a mapping")

    # Validate required fields
    if "kind" not in data:
        raise ValueError("Spec missing required field: kind")
    if "name" not in data:
        raise ValueError("Spec missing required field: name")

    # Extract body (everything after second ---)
    body_lines = lines[end_idx + 1 :]
    data["_body"] = "\n".join(body_lines).strip()

    return data


def get_stages(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract stages from a parsed spec."""
    return spec.get("stages", [])


def get_certification(spec: dict[str, Any]) -> dict[str, Any]:
    """Extract certification requirements from a parsed spec."""
    return spec.get("certification", {})
