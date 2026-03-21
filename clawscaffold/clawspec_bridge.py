"""Optional ClawSpec integration wrappers."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from clawscaffold.clawspec_bootstrap import bootstrap_clawspec

VENDORED_ASSERTION_TYPES = [
    "file_present",
    "file_absent",
    "gateway_healthy",
    "env_present",
    "gateway_response",
    "artifact_exists",
    "artifact_contains",
    "artifact_absent_words",
    "artifact_matches_golden",
    "state_file",
    "log_entry",
    "decision_routed_to",
    "tool_was_called",
    "tool_not_called",
    "delegation_occurred",
    "slack_message_sent",
    "email_received",
    "token_budget",
    "tool_not_permitted",
    "llm_judge",
    "agent_identity_consistent",
    "llm_call_count",
    "tool_sequence",
    "model_used",
    "delegation_path",
    "per_span_budget",
    "trace_token_budget",
    "trace_duration",
    "trace_cost",
    "no_span_errors",
    "tool_not_invoked",
]

VENDORED_REQUIRED_FIELDS: dict[str, dict[str, str]] = {
    "artifact_exists": {"path": "str"},
    "artifact_contains": {"path": "str", "text": "str"},
    "token_budget": {"max_tokens": "int"},
    "tool_not_permitted": {"tool": "str"},
    "llm_judge": {"rubric": "str"},
    "agent_identity_consistent": {"section_id": "str"},
    "llm_call_count": {},  # min or max, at least one
    "tool_sequence": {"expected": "list"},
    "model_used": {},  # expected or not_expected
    "delegation_path": {"expected": "list"},
    "per_span_budget": {"span_type": "str", "max_tokens": "int"},
    "trace_token_budget": {},  # max_input_tokens or max_output_tokens
    "trace_duration": {"max_ms": "float"},
    "trace_cost": {"max_usd": "float"},
    "no_span_errors": {},
    "tool_not_invoked": {"tool": "str"},
}


def _import_module(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        if name == "clawspec" or name.startswith("clawspec."):
            bootstrap_clawspec()
            try:
                return importlib.import_module(name)
            except ImportError:
                return None
        return None


def clawspec_available() -> bool:
    return _import_module("clawspec") is not None


def bridge_warnings() -> list[str]:
    if clawspec_available():
        return []
    return [
        "ClawSpec not installed -- skipping artifact validation",
        "ClawSpec not installed -- manual ledger entry required",
    ]


def validate_artifact(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if file_path.name not in ("SKILL.md", "SOUL.md"):
        return {
            "artifact": str(file_path),
            "valid": None,
            "errors": [],
            "skipped": True,
        }
    clawspec = _import_module("clawspec")
    if clawspec is None:
        return {
            "artifact": str(file_path),
            "valid": None,
            "errors": [],
            "warning": "ClawSpec not installed -- skipping artifact validation",
        }

    raw = clawspec.validate(str(file_path))
    # ValidationReport is a dataclass; access attributes directly, fall back to
    # dict-style access for forward compatibility.
    if hasattr(raw, "passed"):
        valid = bool(raw.passed)
    elif hasattr(raw, "valid"):
        valid = bool(raw.valid)
    else:
        valid = bool(raw.get("valid") if isinstance(raw, dict) else False)
    errors = getattr(raw, "errors", raw.get("errors") if isinstance(raw, dict) else [])
    return {"artifact": str(file_path), "valid": valid, "errors": list(errors or [])}


def list_assertion_types() -> list[str]:
    registry_module = _import_module("clawspec.assertions")
    if registry_module is None:
        return list(VENDORED_ASSERTION_TYPES)
    get_registered = getattr(registry_module, "get_registered_assertions", None)
    if get_registered is not None:
        return sorted(get_registered().keys())
    # Legacy fallback: check for SHIPPED_ASSERTION_TYPES tuple
    shipped = getattr(registry_module, "SHIPPED_ASSERTION_TYPES", None)
    if shipped is not None:
        return list(shipped)
    return list(VENDORED_ASSERTION_TYPES)


def get_required_fields(assertion_type: str) -> dict[str, Any]:
    return dict(VENDORED_REQUIRED_FIELDS.get(assertion_type, {}))


def register_coverage(entry: dict[str, Any] | None = None, /, **kwargs: Any) -> dict[str, Any]:
    payload = dict(entry or {})
    payload.update(kwargs)
    coverage_module = _import_module("clawspec.coverage")
    register = getattr(coverage_module, "register", None) if coverage_module is not None else None
    if coverage_module is not None and register is None:
        return {"registered": True, "mode": "local-ledger-fragment"}
    if register is None:
        return {
            "registered": False,
            "warning": "ClawSpec not installed -- manual ledger entry required",
        }
    register(
        target_id=payload["target_id"],
        tier=payload["tier"],
        status=payload["status"],
        contracts=payload.get("contracts", {}),
        coverage=payload.get("coverage", {}),
        verification=payload.get("verification", {}),
        deferred_hardening=payload.get("deferred_hardening", []),
        notes=payload.get("notes", []),
    )
    return {"registered": True}
