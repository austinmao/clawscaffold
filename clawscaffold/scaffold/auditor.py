"""Pipeline auditor — check spec against requirements."""

from __future__ import annotations

from typing import Any


def audit_pipeline(spec: dict[str, Any]) -> dict[str, list[str]]:
    """Audit a pipeline spec and return findings by severity.

    Severity levels:
    - required: blocks promotion (missing contracts, verification, gates)
    - recommended: runtime risk (unknown agents, no brand gate)
    - optional: quality improvement (test coverage, documentation)
    """
    report: dict[str, list[str]] = {
        "required": [],
        "recommended": [],
        "optional": [],
    }

    stages = spec.get("stages", [])
    certification = spec.get("certification", {})
    stage_ids = {s["id"] for s in stages}

    # Required checks
    _check_certification(certification, report)
    _check_verification_stage(stages, stage_ids, report)
    _check_approval_gate(stages, report)

    # Recommended checks
    _check_unknown_agents(stages, report)
    _check_brand_gate(stages, stage_ids, report)
    _check_stage_outputs(stages, report)

    # Optional checks
    _check_documentation(spec, report)
    _check_stage_count(stages, report)

    return report


def _check_certification(cert: dict[str, Any], report: dict[str, list[str]]) -> None:
    required_certs = cert.get("required", [])
    if not required_certs:
        report["required"].append(
            "No required certifications declared. "
            "Add certification.required[] (e.g., clawspec-contracts, channel-delivery-test)"
        )


def _check_verification_stage(
    stages: list[dict[str, Any]], stage_ids: set[str], report: dict[str, list[str]]
) -> None:
    has_verify = any(
        s.get("type") == "verification" or "verify" in s.get("id", "")
        for s in stages
    )
    if not has_verify:
        report["required"].append(
            "No verification stage found. "
            "Pipeline must include a stage with type: verification or id containing 'verify'"
        )


def _check_approval_gate(stages: list[dict[str, Any]], report: dict[str, list[str]]) -> None:
    has_approval = any(
        s.get("type") == "human-gate" or s.get("agent") == "human-gate"
        for s in stages
    )
    if not has_approval:
        report["required"].append(
            "No human approval gate found. "
            "Pipeline must include a stage with type: human-gate"
        )


def _check_unknown_agents(stages: list[dict[str, Any]], report: dict[str, list[str]]) -> None:
    for s in stages:
        agent = s.get("agent", "")
        if agent == "unknown" or agent == "script:unknown":
            report["recommended"].append(
                f"Stage '{s['id']}' has unknown agent. "
                f"Assign a specific agent ID or script path"
            )


def _check_brand_gate(
    stages: list[dict[str, Any]], stage_ids: set[str], report: dict[str, list[str]]
) -> None:
    has_brand = any(
        "brand" in s.get("id", "").lower() or s.get("verdict") == "required"
        for s in stages
    )
    if not has_brand:
        report["recommended"].append(
            "No brand gate or verdict-required stage found. "
            "Consider adding a stage with verdict: required for quality control"
        )


def _check_stage_outputs(stages: list[dict[str, Any]], report: dict[str, list[str]]) -> None:
    for s in stages:
        if not s.get("agent", "").startswith(("human-gate", "script:")):
            # Agent stages should ideally declare what they produce
            pass  # Not enforced yet — future: check produces[] field


def _check_documentation(spec: dict[str, Any], report: dict[str, list[str]]) -> None:
    body = spec.get("_body", "")
    if len(body) < 50:
        report["optional"].append(
            "Pipeline documentation is sparse. "
            "Add stage descriptions in the spec body"
        )


def _check_stage_count(stages: list[dict[str, Any]], report: dict[str, list[str]]) -> None:
    if len(stages) < 3:
        report["optional"].append(
            f"Pipeline has only {len(stages)} stages. "
            "Consider whether verification, gate, and record-create stages are needed"
        )
