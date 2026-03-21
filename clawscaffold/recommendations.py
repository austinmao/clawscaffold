"""Planner recommendation helpers for the unified scaffold interview system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawscaffold.constants import SOUL_SECTION_ORDER, STANDARD_SKILL_SECTION_ORDER
from clawscaffold.interview import draft_section_content, runtime_file_for_target
from clawscaffold.models import Recommendation, SectionContent, TargetSnapshot
from clawscaffold.utils import canonical_target_path, iter_target_paths, now_iso, read_yaml, sha256_prefix, slug_to_title


def build_target_snapshot(mode: str, kind: str, target_id: str, root: Path) -> TargetSnapshot:
    canonical_path = canonical_target_path(kind, target_id, root)
    runtime_path = runtime_file_for_target(kind, target_id, root)
    canonical_hash = None
    if canonical_path.exists():
        canonical_hash = sha256_prefix(canonical_path.read_text(encoding="utf-8"))
    runtime_hashes: dict[str, str] = {}
    if runtime_path.exists():
        runtime_hashes[runtime_path.name] = sha256_prefix(runtime_path.read_text(encoding="utf-8"))
    return TargetSnapshot(
        target_kind=kind,
        target_id=target_id,
        mode=mode,
        canonical_hash=canonical_hash,
        runtime_hashes=runtime_hashes,
        captured_at=now_iso(),
    )


def compare_snapshot(snapshot: TargetSnapshot, root: Path) -> TargetSnapshot:
    current = build_target_snapshot(snapshot.mode, snapshot.target_kind, snapshot.target_id, root)
    if current.canonical_hash != snapshot.canonical_hash or current.runtime_hashes != snapshot.runtime_hashes:
        current.drift_state = "changed"
        current.drift_reason = "Underlying canonical or runtime content changed after the run started."
    return current


def _required_sections(kind: str) -> list[tuple[str, str]]:
    return SOUL_SECTION_ORDER if kind == "agent" else STANDARD_SKILL_SECTION_ORDER


def _canonical_sections(kind: str, target_id: str, root: Path) -> dict[str, dict]:
    path = canonical_target_path(kind, target_id, root)
    if not path.exists():
        return {}
    spec = read_yaml(path)
    return dict(spec.get(kind, {}).get("sections", {}))


def _nested_value(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _infer_answers(kind: str, target_id: str, sections: dict[str, SectionContent], policy_hints: dict) -> dict[str, str]:
    department = target_id.split("/", 1)[0] if "/" in target_id else target_id
    answers: dict[str, str] = {"identity.domain": department}
    if kind == "agent":
        who_i_am = sections.get("who_i_am")
        answers["identity.purpose"] = (who_i_am.content.split(".")[0].strip() if who_i_am and who_i_am.content else f"support {slug_to_title(target_id)} workflows")
        answers["identity.disposition"] = "direct, grounded, and precise"
        if policy_hints.get("memory", {}).get("retrieval_mode"):
            answers["policy.memory.retrieval_mode"] = policy_hints["memory"]["retrieval_mode"]
    else:
        overview = sections.get("overview") or sections.get("usage")
        answers["skill.purpose"] = overview.content.splitlines()[0].strip() if overview and overview.content else f"Handle {slug_to_title(target_id)} requests"
        answers["skill.trigger"] = f"/{target_id.split('/')[-1]}"
    return answers


def _exemplar_comparison(kind: str, target_id: str, dimension: str, root: Path) -> dict[str, Any] | None:
    path_by_dimension = {
        "cognition_posture": "policy.cognition",
        "operational_autonomy": "operation.approvals",
        "cadence_monitoring": "agent.heartbeat",
        "memory_persistence": "policy.memory",
    }
    dotted_path = path_by_dimension.get(dimension)
    if not dotted_path:
        return None
    department = target_id.split("/", 1)[0]
    prefix = root / "catalog" / f"{kind}s" / department
    if not prefix.exists():
        return None
    for candidate in iter_target_paths(root):
        if candidate == canonical_target_path(kind, target_id, root):
            continue
        if prefix not in candidate.parents:
            continue
        spec = read_yaml(candidate)
        value = _nested_value(spec, dotted_path)
        if value not in (None, {}, []):
            return {"path": str(candidate.relative_to(root)), "value": value}
    return None


def _choose_provenance_basis(
    *,
    schema_validity: bool = False,
    profile_defaults: bool = False,
    target_inference: bool = False,
    exemplar_comparison: bool = False,
) -> str | None:
    if schema_validity:
        return "schema_validity"
    if profile_defaults:
        return "profile_defaults"
    if target_inference:
        return "target_inference"
    if exemplar_comparison:
        return "exemplar_comparison"
    return None


def _make_recommendation(
    kind: str,
    target_id: str,
    section_id: str,
    heading: str,
    sections: dict[str, SectionContent],
    policy_hints: dict,
    root: Path,
    *,
    recommendation_type: str = "missing_standard",
    content: str | None = None,
    source: str = "generated",
    rationale: str | None = None,
    confidence: float = 0.8,
    risk_flags: list[str] | None = None,
    review_required: bool = False,
    decision_bundle: str | None = None,
    blocking_level: str | None = None,
    provenance_basis: str | None = None,
) -> Recommendation:
    answers = _infer_answers(kind, target_id, sections, policy_hints)
    generated_content = content if content is not None else draft_section_content(kind, section_id, answers, root=root)
    flags = list(risk_flags or [])
    if confidence < 0.6 and "low_confidence" not in flags:
        flags.append("low_confidence")
    primary_provenance = provenance_basis or _choose_provenance_basis(
        schema_validity=recommendation_type == "missing_standard",
        target_inference=recommendation_type == "conflict_resolution",
    )
    return Recommendation(
        recommendation_id=f"rec-{section_id}",
        section_id=section_id,
        heading=heading,
        content=generated_content,
        source=source,
        rationale=rationale or f"Recommended to fill the missing standard section '{heading}'.",
        confidence=confidence,
        risk_flags=flags,
        requires_question=True,
        review_required=review_required or bool(flags),
        status="pending",
        recommendation_type=recommendation_type,
        decision_bundle=decision_bundle,
        provenance_basis=primary_provenance,
        blocking_level=blocking_level or ("blocking" if "conflict" in flags else "quality"),
    )


def recommend_sections(
    kind: str,
    target_id: str,
    sections: dict[str, SectionContent],
    policy_hints: dict,
    root: Path,
) -> dict[str, Recommendation]:
    recommendations: dict[str, Recommendation] = {}
    for section_id, heading in _required_sections(kind):
        if section_id in sections:
            continue
        confidence = 0.9 if len(sections) >= 3 else 0.55
        recommendations[section_id] = _make_recommendation(
            kind,
            target_id,
            section_id,
            heading,
            sections,
            policy_hints,
            root,
            confidence=confidence,
            review_required=confidence < 0.6,
            provenance_basis=_choose_provenance_basis(schema_validity=True, profile_defaults=len(sections) >= 3),
            blocking_level="quality",
        )

    canonical_sections = _canonical_sections(kind, target_id, root)
    for section_id, runtime_section in sections.items():
        canonical_section = canonical_sections.get(section_id)
        if not canonical_section:
            continue
        canonical_content = str(canonical_section.get("content", "")).strip()
        if canonical_content and canonical_content != runtime_section.content.strip():
            recommendations[f"conflict-{section_id}"] = _make_recommendation(
                kind,
                target_id,
                section_id,
                runtime_section.heading,
                sections,
                policy_hints,
                root,
                recommendation_type="conflict_resolution",
                content=runtime_section.content,
                source=runtime_section.source,
                rationale=f"Runtime content for '{runtime_section.heading}' differs from the canonical spec and needs operator review.",
                confidence=0.5,
                risk_flags=["conflict"],
                review_required=True,
                provenance_basis=_choose_provenance_basis(target_inference=True),
                blocking_level="blocking",
            )
    return recommendations


def provenance_summary(sections: dict[str, SectionContent]) -> dict[str, int]:
    summary = {"imported": 0, "generated": 0, "authored": 0}
    for section in sections.values():
        summary[section.source] = summary.get(section.source, 0) + 1
    return summary
