"""Delta helpers for existing vs generated ClawSpec artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from clawscaffold.models import ClawSpecArtifacts, ClawSpecDelta
from clawscaffold.utils import now_iso, read_yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_yaml(path)


def _scenario_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scenarios = payload.get("scenarios", [])
    return {item["name"]: item for item in scenarios if isinstance(item, dict) and item.get("name")}


def _normalize_artifacts(target_dir: Path, generated: ClawSpecArtifacts | dict[str, Any]) -> ClawSpecArtifacts:
    if isinstance(generated, ClawSpecArtifacts):
        return generated
    parts = target_dir.parts
    if "agents" in parts:
        idx = parts.index("agents")
        target_kind = "agent"
        target_id = "/".join(parts[idx + 1 :])
    elif "skills" in parts:
        idx = parts.index("skills")
        target_kind = "skill"
        target_id = "/".join(parts[idx + 1 :])
    else:
        target_kind = str(generated.get("target_kind", "skill"))
        target_id = str(generated.get("target_id", target_dir.name))
    return ClawSpecArtifacts(
        target_id=target_id,
        target_kind=target_kind,
        target_tier=str(generated.get("target_tier", "interior-skill")),
        scenarios=generated.get("scenarios"),
        handoff_contracts=dict(generated.get("handoff_contracts", {})),
        pipeline=generated.get("pipeline"),
        ledger_entry=dict(generated.get("ledger_entry", {})),
        staging_dir=str(generated.get("staging_dir", "")),
        validation_results=list(generated.get("validation_results", [])),
        warnings=list(generated.get("warnings", [])),
        generated_at=str(generated.get("generated_at", "")),
    )


def compute_delta(
    *args: Any,
    target_dir: str | Path | None = None,
    generated: ClawSpecArtifacts | dict[str, Any] | None = None,
) -> ClawSpecDelta:
    if args:
        if len(args) == 4 and args[0] in {"agent", "skill"}:
            _kind, target_id, generated_arg, root = args
            target_dir = Path(root) / ("agents" if args[0] == "agent" else "skills") / str(target_id)
            generated = generated_arg
        else:
            raise TypeError("compute_delta expects either keyword arguments or (kind, target_id, generated, root)")
    if target_dir is None or generated is None:
        raise TypeError("compute_delta requires target_dir and generated artifacts")

    runtime_dir = Path(target_dir)
    tests_dir = runtime_dir / "tests"
    artifacts = _normalize_artifacts(runtime_dir, generated)

    existing_scenarios = _load_yaml(tests_dir / "scenarios.yaml")
    existing_pipeline = _load_yaml(tests_dir / "pipeline.yaml")
    existing_handoffs_dir = tests_dir / "handoffs"
    existing_handoffs = {
        path.name: _load_yaml(path)
        for path in sorted(existing_handoffs_dir.glob("*.yaml"))
    } if existing_handoffs_dir.exists() else {}
    existing_ledger = _load_yaml(tests_dir / "ledger-entry.yaml")

    scenario_deltas: list[dict[str, Any]] = []
    current = _scenario_index(existing_scenarios)
    proposed = _scenario_index(artifacts.scenarios or {})
    for name, scenario in proposed.items():
        existing = current.get(name)
        status = "new"
        if existing is not None:
            status = "identical" if existing == scenario else "changed"
        scenario_deltas.append({"name": name, "status": status})

    handoff_deltas: list[dict[str, Any]] = []
    for filename, contract in sorted(artifacts.handoff_contracts.items()):
        existing = existing_handoffs.get(filename)
        status = "new"
        if existing is not None:
            status = "identical" if existing == contract else "changed"
        handoff_deltas.append({"filename": filename, "status": status})

    pipeline_delta: dict[str, Any] | None = None
    if artifacts.pipeline is not None:
        pipeline_delta = {
            "status": "new" if not existing_pipeline else ("identical" if existing_pipeline == artifacts.pipeline else "changed")
        }

    existing_coverage = existing_ledger.get("coverage", {}) if isinstance(existing_ledger, dict) else {}
    proposed_coverage = artifacts.ledger_entry.get("coverage", {}) if artifacts.ledger_entry else {}
    ledger_delta = {
        category: {"current": existing_coverage.get(category), "proposed": value}
        for category, value in proposed_coverage.items()
        if existing_coverage.get(category) != value
    }

    has_existing = bool(existing_scenarios or existing_handoffs or existing_pipeline)
    return ClawSpecDelta(
        target_id=artifacts.target_id,
        has_existing=has_existing,
        baseline_missing=not has_existing,
        scenario_deltas=scenario_deltas,
        handoff_deltas=handoff_deltas,
        pipeline_delta=pipeline_delta,
        ledger_delta=ledger_delta,
        fallback_reason=None if has_existing else "no-baseline-coverage",
        computed_at=now_iso(),
    )


def render_delta_markdown(delta: ClawSpecDelta | dict[str, Any]) -> str:
    payload = delta.to_dict() if hasattr(delta, "to_dict") else dict(delta)
    lines = ["| Artifact | Status |", "|----------|--------|"]
    for item in payload.get("scenario_deltas", []):
        lines.append(f"| scenario:{item['name']} | {item['status']} |")
    for item in payload.get("handoff_deltas", []):
        lines.append(f"| handoff:{item['filename']} | {item['status']} |")
    pipeline = payload.get("pipeline_delta")
    if pipeline:
        lines.append(f"| pipeline.yaml | {pipeline.get('status', 'unknown')} |")
    for category, change in payload.get("ledger_delta", {}).items():
        lines.append(f"| ledger:{category} | {change['current']} -> {change['proposed']} |")
    return "\n".join(lines)


def load_pre_extend_spec(*, kind: str, target_id: str, root: Path) -> dict[str, Any] | None:
    repo_path = f"catalog/{'agents' if kind == 'agent' else 'skills'}/{target_id}.yaml"
    result = subprocess.run(
        ["git", "show", f"HEAD:{repo_path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    data = yaml.safe_load(result.stdout) or {}
    return data if isinstance(data, dict) else None


def compute_delta_elements(previous_spec: dict[str, Any] | None, current_spec: dict[str, Any]) -> dict[str, list[str]]:
    if previous_spec is None:
        return {}
    categories: list[str] = []
    if previous_spec.get("skill", {}).get("permissions", {}) != current_spec.get("skill", {}).get("permissions", {}):
        categories.append("permission")
    if previous_spec.get("policy", {}).get("security", {}) != current_spec.get("policy", {}).get("security", {}):
        categories.append("security")
    previous_sections = (previous_spec.get("agent", {}) or previous_spec.get("skill", {})).get("sections", {})
    current_sections = (current_spec.get("agent", {}) or current_spec.get("skill", {})).get("sections", {})
    if previous_sections != current_sections:
        categories.append("boundary")
    return {"categories": sorted(set(categories)), "delegations": []} if categories else {}
