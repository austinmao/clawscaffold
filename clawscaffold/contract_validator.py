"""Handoff contract YAML schema validator for the multi-agent pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

_VALID_ASSERTION_KEYS = frozenset(
    {"file_exists", "contains", "not_contains", "word_count_max", "word_count_min",
     "api_called", "api_response_status"}
)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Handoff Contract",
    "type": "object",
    "required": ["type", "pipeline", "stage", "from", "to", "binding", "delegated", "artifact_path", "verification"],
    "additionalProperties": False,
    "properties": {
        "type": {"const": "handoff-contract"},
        "pipeline": {"type": "string", "minLength": 1},
        "stage": {"type": "string", "minLength": 1},
        "from": {"type": "string", "minLength": 1},
        "to": {"type": "string", "minLength": 1},
        "binding": {"type": "object"},
        "delegated": {"type": "object"},
        "artifact_path": {"type": "string", "minLength": 1},
        "verification": {
            "type": "array",
            "items": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 1,
            },
        },
        "created_at": {"type": "string"},
        "prior_work": {"type": "object"},
        "created_at": {"type": "string"},
    },
}


class ContractValidationError(ValueError):
    """Raised when a handoff contract does not match the expected schema."""


def _validate_assertion_keys(verification: list[Any]) -> list[str]:
    """Return a list of error messages for malformed verification entries."""
    errors: list[str] = []
    for index, entry in enumerate(verification):
        if not isinstance(entry, dict):
            errors.append(f"verification[{index}]: expected a mapping, got {type(entry).__name__}")
            continue
        if len(entry) != 1:
            errors.append(
                f"verification[{index}]: each entry must have exactly one key, got {list(entry.keys())}"
            )
            continue
        key = next(iter(entry))
        if key not in _VALID_ASSERTION_KEYS:
            errors.append(
                f"verification[{index}]: unknown assertion type '{key}'; "
                f"allowed: {sorted(_VALID_ASSERTION_KEYS)}"
            )
    return errors


def validate_contract(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a loaded contract dict against the handoff contract schema.

    Raises ContractValidationError if validation fails.
    Returns the input dict unchanged on success.
    """
    validator = Draft202012Validator(_SCHEMA)
    schema_errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if schema_errors:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in schema_errors
        )
        raise ContractValidationError(details)

    verification = data.get("verification", [])
    key_errors = _validate_assertion_keys(verification)
    if key_errors:
        raise ContractValidationError("; ".join(key_errors))

    return data


def validate_contract_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML file from disk and validate it as a handoff contract.

    Raises ContractValidationError if the file cannot be parsed or is invalid.
    Returns the validated contract dict on success.
    """
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except OSError as exc:
        raise ContractValidationError(f"Cannot read contract file '{file_path}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise ContractValidationError(f"YAML parse error in '{file_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ContractValidationError(
            f"Contract file '{file_path}' must be a YAML mapping, got {type(data).__name__}"
        )

    return validate_contract(data)
