"""Assertion runner: verifies output artifacts against handoff contract rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clawscaffold.contract_validator import validate_contract


@dataclass
class AssertionResult:
    """Result of running all verification assertions in a handoff contract."""

    passed: bool
    total: int
    failures: list[dict[str, str]] = field(default_factory=list)


def _load_contract(contract_path: Path) -> dict[str, Any]:
    """Read and validate the contract YAML from disk."""
    try:
        raw = contract_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except OSError as exc:
        raise FileNotFoundError(
            f"Cannot read contract file '{contract_path}': {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error in '{contract_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Contract file '{contract_path}' must be a YAML mapping"
        )

    return validate_contract(data)


def _read_artifact(artifact_path: Path) -> str:
    """Return the text content of an artifact file."""
    return artifact_path.read_text(encoding="utf-8")


def _count_words(text: str) -> int:
    """Return the number of whitespace-delimited words in text."""
    return len(text.split())


def _is_payload_subset(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Check if all key-value pairs in *expected* are present in *actual*."""
    return all(k in actual and actual[k] == v for k, v in expected.items())


def _run_audit_assertion(
    key: str,
    spec: dict[str, Any],
) -> dict[str, str] | None:
    """Handle api_called and api_response_status assertions against an audit log."""
    audit_log_path = Path(str(spec.get("audit_log", "")))
    if not audit_log_path.exists():
        return {
            "type": key,
            "detail": f"Audit log not found: {audit_log_path}",
        }

    raw = audit_log_path.read_text(encoding="utf-8")
    entries = yaml.safe_load(raw)
    if not isinstance(entries, list):
        entries = []

    action_filter = spec.get("action")
    matching = [e for e in entries if e.get("action") == action_filter]

    if key == "api_called":
        method_filter = spec.get("method")
        if method_filter:
            matching = [e for e in matching if e.get("method") == method_filter]

        payload_expected = spec.get("payload_contains")
        if payload_expected and isinstance(payload_expected, dict):
            matching = [
                e for e in matching
                if isinstance(e.get("payload"), dict)
                and _is_payload_subset(payload_expected, e["payload"])
            ]

        if not matching:
            return {
                "type": "api_called",
                "detail": f"No matching API call found for action: {action_filter}",
            }
        return None

    if key == "api_response_status":
        expected_status = int(spec.get("expected_status", 0))
        matching_status = [
            e for e in matching if e.get("response_status") == expected_status
        ]
        if not matching_status:
            actual = [e.get("response_status") for e in matching] if matching else []
            return {
                "type": "api_response_status",
                "detail": (
                    f"Expected response status {expected_status} for action "
                    f"{action_filter!r}, got {actual}"
                ),
            }
        return None

    return {"type": key, "detail": f"Unknown audit assertion type: {key!r}"}


def _run_assertion(
    assertion: dict[str, Any],
    artifact_path: Path,
    artifact_text: str | None,
) -> dict[str, str] | None:
    """Run one assertion entry. Returns a failure dict or None on pass."""
    key = next(iter(assertion))
    value = assertion[key]

    # Audit-log-based assertions (self-contained, don't need artifact)
    if key in ("api_called", "api_response_status"):
        if not isinstance(value, dict):
            return {"type": key, "detail": f"{key} value must be a mapping"}
        return _run_audit_assertion(key, value)

    if key == "file_exists":
        if not artifact_path.exists():
            return {"type": "file_exists", "detail": f"File not found: {artifact_path}"}
        return None

    if artifact_text is None:
        return {
            "type": key,
            "detail": f"Artifact file not found: {artifact_path}",
        }

    if key == "contains":
        if str(value) not in artifact_text:
            return {"type": "contains", "detail": f"String not found: {value!r}"}
        return None

    if key == "not_contains":
        if str(value) in artifact_text:
            return {"type": "not_contains", "detail": f"Forbidden string found: {value!r}"}
        return None

    if key == "word_count_max":
        count = _count_words(artifact_text)
        if count > int(value):
            return {
                "type": "word_count_max",
                "detail": f"Word count {count} exceeds maximum {value}",
            }
        return None

    if key == "word_count_min":
        count = _count_words(artifact_text)
        if count < int(value):
            return {
                "type": "word_count_min",
                "detail": f"Word count {count} is below minimum {value}",
            }
        return None

    return {"type": key, "detail": f"Unknown assertion type: {key!r}"}


def run_assertions(contract_path: str, workspace_root: str) -> AssertionResult:
    """Run all verification assertions defined in a handoff contract.

    Reads the contract at `contract_path`, resolves `artifact_path` relative to
    `workspace_root`, and evaluates each assertion in the `verification` list.

    Args:
        contract_path: Absolute or relative path to the contract YAML file.
        workspace_root: Root directory used to resolve artifact_path.

    Returns:
        AssertionResult with passed, total, and failures populated.

    Raises:
        ContractValidationError: If the contract YAML is invalid.
        ValueError: If the contract YAML cannot be parsed.
        FileNotFoundError: If the contract file cannot be read.
    """
    resolved_contract = Path(contract_path)
    resolved_root = Path(workspace_root)

    contract = _load_contract(resolved_contract)
    verification: list[dict[str, Any]] = contract.get("verification", [])
    artifact_rel: str = contract["artifact_path"]
    artifact_path = resolved_root / artifact_rel

    artifact_text: str | None = None
    if artifact_path.exists():
        artifact_text = _read_artifact(artifact_path)

    failures: list[dict[str, str]] = []
    for assertion in verification:
        result = _run_assertion(assertion, artifact_path, artifact_text)
        if result is not None:
            failures.append(result)

    return AssertionResult(
        passed=len(failures) == 0,
        total=len(verification),
        failures=failures,
    )
