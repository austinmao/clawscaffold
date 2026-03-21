"""Schema validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from clawscaffold.paths import compiler_root, repo_root
from clawscaffold.utils import read_yaml


class SchemaValidationError(ValueError):
    """Raised when a document does not match its schema."""


def load_schema(schema_name: str, root: Path | None = None) -> dict[str, Any]:
    schema_path = compiler_root(root or repo_root()) / "schemas" / schema_name
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_dict(data: dict[str, Any], schema_name: str, root: Path | None = None) -> dict[str, Any]:
    schema = load_schema(schema_name, root)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda item: list(item.path))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise SchemaValidationError(details)
    return data


def validate_yaml_file(path: str | Path, schema_name: str, root: Path | None = None) -> dict[str, Any]:
    file_path = Path(path)
    data = read_yaml(file_path)
    return validate_dict(data, schema_name, root)
