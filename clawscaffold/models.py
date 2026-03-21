"""Typed dataclasses for compiler entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CONFIG_CLASSIFICATIONS = {"explicit", "inferred", "missing", "nonstandard_gap"}
_RISK_LEVELS = {"low", "medium", "high"}
_BUNDLE_IDS = {
    "cognition_posture",
    "operational_autonomy",
    "cadence_monitoring",
    "memory_persistence",
    "org_hierarchy",
    "coordination_pattern",
    "escalation_chain",
    "resource_limits",
    "data_classification",
    "observability_posture",
    "resilience_pattern",
    "scheduling_constraints",
}
_BLOCKING_LEVELS = {"blocking", "stabilizing", "quality"}
_INTENT_SIGNAL_TYPES = {
    "preservation_first",
    "prefers_minimal_interruption",
    "wants_explicit_config",
    "low_autonomy_preference",
}


def _require_choice(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise ValueError(f"Invalid {field_name}: {value}")


def _require_confidence(value: float, field_name: str = "confidence") -> None:
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0")


def _copy_choices(choices: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(choice) for choice in (choices or [])]


def _copy_dicts(entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(entry) for entry in (entries or [])]


@dataclass
class SectionContent:
    id: str
    heading: str
    content: str
    source: str
    custom: bool
    order: int
    content_hash: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectionContent:
        return cls(
            id=data["id"],
            heading=data["heading"],
            content=data.get("content", ""),
            source=data.get("source", "generated"),
            custom=bool(data.get("custom", False)),
            order=int(data.get("order", 0)),
            content_hash=data.get("content_hash"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "heading": self.heading,
            "content": self.content,
            "source": self.source,
            "custom": self.custom,
            "order": self.order,
        }
        if self.content_hash:
            data["content_hash"] = self.content_hash
        return data


@dataclass
class ConfigFinding:
    dimension: str
    bundle: str
    classification: str
    confidence: float
    risk_level: str
    schema_path: str | None = None
    inferred_value: Any = None
    explicit_value: Any = None
    inference_basis: str | None = None
    question_reason: str | None = None

    def __post_init__(self) -> None:
        _require_choice(self.classification, _CONFIG_CLASSIFICATIONS, "classification")
        _require_choice(self.risk_level, _RISK_LEVELS, "risk_level")
        _require_confidence(self.confidence)
        if self.classification == "nonstandard_gap" and self.schema_path is not None:
            raise ValueError("nonstandard_gap findings must not declare schema_path")
        if self.classification == "explicit" and self.explicit_value is None:
            raise ValueError("explicit findings must declare explicit_value")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigFinding:
        return cls(
            dimension=data["dimension"],
            bundle=data["bundle"],
            classification=data["classification"],
            confidence=float(data.get("confidence", 0.0)),
            risk_level=data.get("risk_level", "low"),
            schema_path=data.get("schema_path"),
            inferred_value=data.get("inferred_value"),
            explicit_value=data.get("explicit_value"),
            inference_basis=data.get("inference_basis"),
            question_reason=data.get("question_reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "dimension": self.dimension,
            "bundle": self.bundle,
            "classification": self.classification,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
        }
        if self.schema_path is not None:
            data["schema_path"] = self.schema_path
        if self.inferred_value is not None:
            data["inferred_value"] = self.inferred_value
        if self.explicit_value is not None:
            data["explicit_value"] = self.explicit_value
        if self.inference_basis:
            data["inference_basis"] = self.inference_basis
        if self.question_reason:
            data["question_reason"] = self.question_reason
        return data


@dataclass
class DecisionBundle:
    bundle_id: str
    display_name: str
    description: str
    findings: list[ConfigFinding] = field(default_factory=list)
    aggregate_risk: str = "low"
    aggregate_confidence: float = 0.0
    recommendation: str | None = None
    provenance_basis: str | None = None
    blocking_level: str = "quality"

    def __post_init__(self) -> None:
        _require_choice(self.bundle_id, _BUNDLE_IDS, "bundle_id")
        _require_choice(self.aggregate_risk, _RISK_LEVELS, "aggregate_risk")
        _require_choice(self.blocking_level, _BLOCKING_LEVELS, "blocking_level")
        _require_confidence(self.aggregate_confidence, "aggregate_confidence")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionBundle:
        return cls(
            bundle_id=data["bundle_id"],
            display_name=data.get("display_name", ""),
            description=data.get("description", ""),
            findings=[ConfigFinding.from_dict(item) for item in data.get("findings", [])],
            aggregate_risk=data.get("aggregate_risk", "low"),
            aggregate_confidence=float(data.get("aggregate_confidence", 0.0)),
            recommendation=data.get("recommendation"),
            provenance_basis=data.get("provenance_basis"),
            blocking_level=data.get("blocking_level", "quality"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "bundle_id": self.bundle_id,
            "display_name": self.display_name,
            "description": self.description,
            "findings": [item.to_dict() for item in self.findings],
            "aggregate_risk": self.aggregate_risk,
            "aggregate_confidence": self.aggregate_confidence,
            "blocking_level": self.blocking_level,
        }
        if self.recommendation:
            data["recommendation"] = self.recommendation
        if self.provenance_basis:
            data["provenance_basis"] = self.provenance_basis
        return data


@dataclass
class IntentSignal:
    signal_type: str
    confidence: float
    active: bool
    last_updated_at: str

    def __post_init__(self) -> None:
        _require_choice(self.signal_type, _INTENT_SIGNAL_TYPES, "signal_type")
        _require_confidence(self.confidence)
        self.active = self.confidence >= 0.5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentSignal:
        return cls(
            signal_type=data["signal_type"],
            confidence=float(data.get("confidence", 0.0)),
            active=bool(data.get("active", False)),
            last_updated_at=data.get("last_updated_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "confidence": self.confidence,
            "active": self.active,
            "last_updated_at": self.last_updated_at,
        }


@dataclass
class DepthMode:
    mode: str
    hard_stop_triggers: list[str] = field(default_factory=list)
    weighted_score: float = 0.0
    score_threshold: float = 3.0
    transition_reason: str | None = None

    def __post_init__(self) -> None:
        _require_choice(self.mode, {"light", "deep"}, "mode")
        if self.hard_stop_triggers and self.mode != "deep":
            raise ValueError("hard-stop triggers require deep mode")
        if self.weighted_score >= self.score_threshold and self.mode != "deep":
            raise ValueError("weighted scores above threshold require deep mode")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DepthMode:
        return cls(
            mode=data["mode"],
            hard_stop_triggers=list(data.get("hard_stop_triggers", [])),
            weighted_score=float(data.get("weighted_score", 0.0)),
            score_threshold=float(data.get("score_threshold", 3.0)),
            transition_reason=data.get("transition_reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "mode": self.mode,
            "hard_stop_triggers": list(self.hard_stop_triggers),
            "weighted_score": self.weighted_score,
            "score_threshold": self.score_threshold,
        }
        if self.transition_reason:
            data["transition_reason"] = self.transition_reason
        return data


@dataclass
class InterviewQuestion:
    id: str
    topic_group: str
    question_type: str
    prompt_text: str
    choices: list[dict[str, Any]] = field(default_factory=list)
    extracted_value: Any = None
    recommended_choice: str | None = None
    answer: Any = None
    draft_content: str | None = None
    answered_at: str | None = None
    recommendation_id: str | None = None
    full_text_visible: bool = False
    decision_bundle: str | None = None
    structured_reason: str | None = None
    provenance_basis: str | None = None
    confidence_band: str | None = None
    risk_level: str | None = None
    blocking_level: str | None = None
    batch_eligible: bool = False
    tradeoff_note: str | None = None
    hidden_assumption: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterviewQuestion:
        return cls(
            id=data["id"],
            topic_group=data["topic_group"],
            question_type=data["question_type"],
            prompt_text=data["prompt_text"],
            choices=_copy_choices(data.get("choices")),
            extracted_value=data.get("extracted_value"),
            recommended_choice=data.get("recommended_choice"),
            answer=data.get("answer"),
            draft_content=data.get("draft_content"),
            answered_at=data.get("answered_at"),
            recommendation_id=data.get("recommendation_id"),
            full_text_visible=bool(data.get("full_text_visible", False)),
            decision_bundle=data.get("decision_bundle"),
            structured_reason=data.get("structured_reason"),
            provenance_basis=data.get("provenance_basis"),
            confidence_band=data.get("confidence_band"),
            risk_level=data.get("risk_level"),
            blocking_level=data.get("blocking_level"),
            batch_eligible=bool(data.get("batch_eligible", False)),
            tradeoff_note=data.get("tradeoff_note"),
            hidden_assumption=data.get("hidden_assumption"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "topic_group": self.topic_group,
            "question_type": self.question_type,
            "prompt_text": self.prompt_text,
            "choices": _copy_choices(self.choices),
            "extracted_value": self.extracted_value,
            "recommended_choice": self.recommended_choice,
            "answer": self.answer,
            "draft_content": self.draft_content,
            "answered_at": self.answered_at,
            "recommendation_id": self.recommendation_id,
            "full_text_visible": self.full_text_visible,
        }
        if self.decision_bundle:
            data["decision_bundle"] = self.decision_bundle
        if self.structured_reason:
            data["structured_reason"] = self.structured_reason
        if self.provenance_basis:
            data["provenance_basis"] = self.provenance_basis
        if self.confidence_band:
            data["confidence_band"] = self.confidence_band
        if self.risk_level:
            data["risk_level"] = self.risk_level
        if self.blocking_level:
            data["blocking_level"] = self.blocking_level
        if self.batch_eligible:
            data["batch_eligible"] = True
        if self.tradeoff_note:
            data["tradeoff_note"] = self.tradeoff_note
        if self.hidden_assumption:
            data["hidden_assumption"] = self.hidden_assumption
        return data


@dataclass
class TargetSnapshot:
    target_kind: str
    target_id: str
    mode: str
    canonical_hash: str | None = None
    runtime_hashes: dict[str, str] = field(default_factory=dict)
    captured_at: str = ""
    drift_state: str = "clean"
    drift_reason: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetSnapshot:
        return cls(
            target_kind=data["target_kind"],
            target_id=data["target_id"],
            mode=data["mode"],
            canonical_hash=data.get("canonical_hash"),
            runtime_hashes=dict(data.get("runtime_hashes", {})),
            captured_at=data.get("captured_at", ""),
            drift_state=data.get("drift_state", "clean"),
            drift_reason=data.get("drift_reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "mode": self.mode,
            "canonical_hash": self.canonical_hash,
            "runtime_hashes": dict(self.runtime_hashes),
            "captured_at": self.captured_at,
            "drift_state": self.drift_state,
        }
        if self.drift_reason:
            data["drift_reason"] = self.drift_reason
        return data


@dataclass
class Recommendation:
    recommendation_id: str
    section_id: str
    heading: str
    content: str
    source: str
    rationale: str
    confidence: float
    risk_flags: list[str] = field(default_factory=list)
    requires_question: bool = True
    review_required: bool = False
    status: str = "pending"
    recommendation_type: str = "missing_standard"
    decision_bundle: str | None = None
    provenance_basis: str | None = None
    blocking_level: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recommendation:
        return cls(
            recommendation_id=data["recommendation_id"],
            section_id=data["section_id"],
            heading=data.get("heading", ""),
            content=data.get("content", ""),
            source=data.get("source", "generated"),
            rationale=data.get("rationale", ""),
            confidence=float(data.get("confidence", 0.0)),
            risk_flags=list(data.get("risk_flags", [])),
            requires_question=bool(data.get("requires_question", True)),
            review_required=bool(data.get("review_required", False)),
            status=data.get("status", "pending"),
            recommendation_type=data.get("recommendation_type", "missing_standard"),
            decision_bundle=data.get("decision_bundle"),
            provenance_basis=data.get("provenance_basis"),
            blocking_level=data.get("blocking_level"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "recommendation_id": self.recommendation_id,
            "section_id": self.section_id,
            "heading": self.heading,
            "content": self.content,
            "source": self.source,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "risk_flags": list(self.risk_flags),
            "requires_question": self.requires_question,
            "review_required": self.review_required,
            "status": self.status,
            "recommendation_type": self.recommendation_type,
        }
        if self.decision_bundle:
            data["decision_bundle"] = self.decision_bundle
        if self.provenance_basis:
            data["provenance_basis"] = self.provenance_basis
        if self.blocking_level:
            data["blocking_level"] = self.blocking_level
        return data


@dataclass
class ReviewableDraft:
    run_id: str
    target_kind: str
    target_id: str
    canonical_spec_path: str
    rendered_preview_paths: list[str] = field(default_factory=list)
    provenance_summary: dict[str, int] = field(default_factory=dict)
    flagged_recommendations: list[str] = field(default_factory=list)
    ready_for_apply: bool = True
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewableDraft:
        return cls(
            run_id=data["run_id"],
            target_kind=data["target_kind"],
            target_id=data["target_id"],
            canonical_spec_path=data["canonical_spec_path"],
            rendered_preview_paths=list(data.get("rendered_preview_paths", [])),
            provenance_summary={str(key): int(value) for key, value in dict(data.get("provenance_summary", {})).items()},
            flagged_recommendations=list(data.get("flagged_recommendations", [])),
            ready_for_apply=bool(data.get("ready_for_apply", True)),
            created_at=data.get("created_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "canonical_spec_path": self.canonical_spec_path,
            "rendered_preview_paths": list(self.rendered_preview_paths),
            "provenance_summary": dict(self.provenance_summary),
            "flagged_recommendations": list(self.flagged_recommendations),
            "ready_for_apply": self.ready_for_apply,
            "created_at": self.created_at,
        }


@dataclass
class InterviewState:
    run_id: str
    mode: str
    target_kind: str
    target_id: str
    builder_identity: str
    execution_style: str = "interactive"
    sections: dict[str, SectionContent] = field(default_factory=dict)
    policy_hints: dict[str, Any] = field(default_factory=dict)
    questions: list[InterviewQuestion] = field(default_factory=list)
    current_question_index: int = 0
    answers: dict[str, Any] = field(default_factory=dict)
    pass_number: int = 1
    content_hash: str | None = None
    status: str = "in_progress"
    created_at: str = ""
    updated_at: str = ""
    execution_env: str | None = None
    snapshot: TargetSnapshot | None = None
    recommendations: dict[str, Recommendation] = field(default_factory=dict)
    reviewable_draft: ReviewableDraft | None = None
    depth_mode: DepthMode | None = None
    config_findings: list[ConfigFinding] = field(default_factory=list)
    decision_bundles: list[DecisionBundle] = field(default_factory=list)
    intent_signals: list[IntentSignal] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterviewState:
        return cls(
            run_id=data["run_id"],
            mode=data["mode"],
            target_kind=data["target_kind"],
            target_id=data["target_id"],
            builder_identity=data["builder_identity"],
            execution_style=data.get("execution_style", "interactive"),
            sections={
                section_id: SectionContent.from_dict(section)
                for section_id, section in data.get("sections", {}).items()
            },
            policy_hints=dict(data.get("policy_hints", {})),
            questions=[InterviewQuestion.from_dict(question) for question in data.get("questions", [])],
            current_question_index=int(data.get("current_question_index", 0)),
            answers=dict(data.get("answers", {})),
            pass_number=int(data.get("pass_number", 1)),
            content_hash=data.get("content_hash"),
            status=data.get("status", "in_progress"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            execution_env=data.get("execution_env"),
            snapshot=TargetSnapshot.from_dict(data["snapshot"]) if data.get("snapshot") else None,
            recommendations={
                recommendation_id: Recommendation.from_dict(recommendation)
                for recommendation_id, recommendation in data.get("recommendations", {}).items()
            },
            reviewable_draft=ReviewableDraft.from_dict(data["reviewable_draft"]) if data.get("reviewable_draft") else None,
            depth_mode=DepthMode.from_dict(data["depth_mode"]) if data.get("depth_mode") else None,
            config_findings=[ConfigFinding.from_dict(item) for item in data.get("config_findings", [])],
            decision_bundles=[DecisionBundle.from_dict(item) for item in data.get("decision_bundles", [])],
            intent_signals=[IntentSignal.from_dict(item) for item in data.get("intent_signals", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "run_id": self.run_id,
            "mode": self.mode,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "builder_identity": self.builder_identity,
            "execution_style": self.execution_style,
            "sections": {section_id: section.to_dict() for section_id, section in self.sections.items()},
            "policy_hints": dict(self.policy_hints),
            "questions": [question.to_dict() for question in self.questions],
            "current_question_index": self.current_question_index,
            "answers": dict(self.answers),
            "pass_number": self.pass_number,
            "content_hash": self.content_hash,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "execution_env": self.execution_env,
        }
        if self.snapshot:
            data["snapshot"] = self.snapshot.to_dict()
        if self.recommendations:
            data["recommendations"] = {
                recommendation_id: recommendation.to_dict()
                for recommendation_id, recommendation in self.recommendations.items()
            }
        if self.reviewable_draft:
            data["reviewable_draft"] = self.reviewable_draft.to_dict()
        if self.depth_mode:
            data["depth_mode"] = self.depth_mode.to_dict()
        if self.config_findings:
            data["config_findings"] = [item.to_dict() for item in self.config_findings]
        if self.decision_bundles:
            data["decision_bundles"] = [item.to_dict() for item in self.decision_bundles]
        if self.intent_signals:
            data["intent_signals"] = [item.to_dict() for item in self.intent_signals]
        return data

    def save(self, path: Path) -> Path:
        from clawscaffold.utils import write_json

        write_json(path, self.to_dict())
        return path

    @classmethod
    def load(cls, path: Path) -> InterviewState:
        from clawscaffold.utils import read_json

        return cls.from_dict(read_json(path))


@dataclass
class ContentLossReport:
    target_id: str
    target_kind: str
    live_path: str
    rendered_path: str
    live_line_count: int
    preserved_line_count: int
    preservation_pct: float
    lines_lost: list[str] = field(default_factory=list)
    lines_added: list[str] = field(default_factory=list)
    passed: bool = True
    computed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "live_path": self.live_path,
            "rendered_path": self.rendered_path,
            "live_line_count": self.live_line_count,
            "preserved_line_count": self.preserved_line_count,
            "preservation_pct": self.preservation_pct,
            "lines_lost": list(self.lines_lost),
            "lines_added": list(self.lines_added),
            "passed": self.passed,
            "computed_at": self.computed_at,
        }


@dataclass
class ClawSpecArtifacts:
    target_id: str
    target_kind: str
    target_tier: str
    scenarios: dict[str, Any] | None = None
    handoff_contracts: dict[str, dict[str, Any]] = field(default_factory=dict)
    pipeline: dict[str, Any] | None = None
    ledger_entry: dict[str, Any] | None = None
    staging_dir: str = ""
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    child_artifacts: list[ClawSpecArtifacts] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "target_tier": self.target_tier,
            "handoff_contracts": {name: dict(contract) for name, contract in self.handoff_contracts.items()},
            "staging_dir": self.staging_dir,
            "validation_results": _copy_dicts(self.validation_results),
            "warnings": list(self.warnings),
            "generated_at": self.generated_at,
        }
        if self.scenarios is not None:
            data["scenarios"] = dict(self.scenarios)
        if self.pipeline is not None:
            data["pipeline"] = dict(self.pipeline)
        if self.ledger_entry is not None:
            data["ledger_entry"] = dict(self.ledger_entry)
        if self.child_artifacts:
            data["child_artifacts"] = [artifact.to_dict() for artifact in self.child_artifacts]
        return data


@dataclass
class ClawSpecDelta:
    target_id: str
    has_existing: bool
    baseline_missing: bool = False
    scenario_deltas: list[dict[str, Any]] = field(default_factory=list)
    handoff_deltas: list[dict[str, Any]] = field(default_factory=list)
    pipeline_delta: dict[str, Any] | None = None
    ledger_delta: dict[str, Any] = field(default_factory=dict)
    delta_elements: dict[str, list[str]] = field(default_factory=dict)
    fallback_reason: str | None = None
    computed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "target_id": self.target_id,
            "has_existing": self.has_existing,
            "baseline_missing": self.baseline_missing,
            "scenario_deltas": _copy_dicts(self.scenario_deltas),
            "handoff_deltas": _copy_dicts(self.handoff_deltas),
            "ledger_delta": dict(self.ledger_delta),
            "delta_elements": {key: list(values) for key, values in self.delta_elements.items()},
            "computed_at": self.computed_at,
        }
        if self.pipeline_delta is not None:
            data["pipeline_delta"] = dict(self.pipeline_delta)
        if self.fallback_reason:
            data["fallback_reason"] = self.fallback_reason
        return data


@dataclass
class ClawSpecDecisions:
    run_id: str
    target_id: str
    decisions: dict[str, str] = field(default_factory=dict)
    decided_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClawSpecDecisions:
        return cls(
            run_id=data["run_id"],
            target_id=data["target_id"],
            decisions=dict(data.get("decisions", {})),
            decided_at=data.get("decided_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "target_id": self.target_id,
            "decisions": dict(self.decisions),
            "decided_at": self.decided_at,
        }


@dataclass
class AuditReport:
    target_id: str
    target_kind: str
    mode: str
    structural_checks: list[dict[str, Any]] = field(default_factory=list)
    heuristic_findings: list[dict[str, Any]] = field(default_factory=list)
    cross_references: list[dict[str, Any]] = field(default_factory=list)
    behavioral_tests: list[dict[str, Any]] = field(default_factory=list)
    structural_pass_rate: float = 0.0
    confidence_score: float = 0.0
    review_priority: str = "informational"
    clawspec_artifacts: ClawSpecArtifacts | None = None
    clawspec_delta: ClawSpecDelta | None = None
    clawspec_valid: bool | None = None
    clawspec_warnings: list[str] = field(default_factory=list)
    computed_at: str = ""

    def compute_confidence(self) -> float:
        structural_total = len(self.structural_checks)
        structural_passed = sum(1 for check in self.structural_checks if check.get("passed"))
        self.structural_pass_rate = structural_passed / structural_total if structural_total else 1.0

        heuristic_total = len(self.heuristic_findings)
        heuristic_penalty = 0.0
        for finding in self.heuristic_findings:
            severity = str(finding.get("severity", "info")).lower()
            if severity == "error":
                heuristic_penalty += 1.0
            elif severity == "warning":
                heuristic_penalty += 0.5
        heuristic_score = 1.0 if heuristic_total == 0 else max(0.0, 1.0 - (heuristic_penalty / heuristic_total))

        cross_total = len(self.cross_references)
        cross_resolved = sum(1 for finding in self.cross_references if finding.get("resolved"))
        cross_score = cross_resolved / cross_total if cross_total else 1.0

        behavioral_total = len(self.behavioral_tests)
        behavioral_passed = sum(1 for finding in self.behavioral_tests if finding.get("passed"))
        behavioral_score = behavioral_passed / behavioral_total if behavioral_total else 1.0

        if self.clawspec_valid is None:
            weighted = (
                (self.structural_pass_rate * 0.5)
                + (heuristic_score * 0.2)
                + (cross_score * 0.2)
                + (behavioral_score * 0.1)
            )
        else:
            validation_results = self.clawspec_artifacts.validation_results if self.clawspec_artifacts else []
            invalid_count = sum(1 for item in validation_results if item.get("valid") is False)
            for child in self.clawspec_artifacts.child_artifacts if self.clawspec_artifacts else []:
                invalid_count += sum(1 for item in child.validation_results if item.get("valid") is False)
            clawspec_score = 1.0 if self.clawspec_valid else 0.0
            weighted = (
                (self.structural_pass_rate * 0.4)
                + (heuristic_score * 0.2)
                + (cross_score * 0.2)
                + (behavioral_score * 0.1)
                + (clawspec_score * 0.1)
            )
            weighted = max(0.0, weighted - (invalid_count * 0.1))

        self.confidence_score = round(weighted * 100, 2)
        return self.confidence_score

    def to_dict(self) -> dict[str, Any]:
        data = {
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "mode": self.mode,
            "structural_checks": _copy_dicts(self.structural_checks),
            "heuristic_findings": _copy_dicts(self.heuristic_findings),
            "cross_references": _copy_dicts(self.cross_references),
            "behavioral_tests": _copy_dicts(self.behavioral_tests),
            "structural_pass_rate": self.structural_pass_rate,
            "confidence_score": self.confidence_score,
            "review_priority": self.review_priority,
            "clawspec_valid": self.clawspec_valid,
            "clawspec_warnings": list(self.clawspec_warnings),
            "computed_at": self.computed_at,
        }
        if self.clawspec_artifacts is not None:
            data["clawspec_artifacts"] = self.clawspec_artifacts.to_dict()
        if self.clawspec_delta is not None:
            data["clawspec_delta"] = self.clawspec_delta.to_dict()
        return data


@dataclass
class ReviewBrief:
    target_id: str
    target_kind: str
    mode: str
    builder_identity: str
    summary: str
    key_decisions: list[dict[str, Any]] = field(default_factory=list)
    audit_findings: list[dict[str, Any]] = field(default_factory=list)
    confidence_score: float = 0.0
    confidence_breakdown: dict[str, float] = field(default_factory=dict)
    suggested_focus: list[str] = field(default_factory=list)
    rendered_preview_paths: list[str] = field(default_factory=list)
    provenance_summary: dict[str, int] = field(default_factory=dict)
    flagged_recommendations: list[str] = field(default_factory=list)
    clawspec_artifact_choices: list[dict[str, Any]] = field(default_factory=list)
    clawspec_delta_report: str = ""
    clawspec_warnings: list[str] = field(default_factory=list)
    transcript_path: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "mode": self.mode,
            "builder_identity": self.builder_identity,
            "summary": self.summary,
            "key_decisions": _copy_dicts(self.key_decisions),
            "audit_findings": _copy_dicts(self.audit_findings),
            "confidence_score": self.confidence_score,
            "confidence_breakdown": dict(self.confidence_breakdown),
            "suggested_focus": list(self.suggested_focus),
            "rendered_preview_paths": list(self.rendered_preview_paths),
            "provenance_summary": dict(self.provenance_summary),
            "flagged_recommendations": list(self.flagged_recommendations),
            "clawspec_artifact_choices": _copy_dicts(self.clawspec_artifact_choices),
            "clawspec_delta_report": self.clawspec_delta_report,
            "clawspec_warnings": list(self.clawspec_warnings),
            "transcript_path": self.transcript_path,
            "created_at": self.created_at,
        }

    def render_markdown(self) -> str:
        lines = [
            f"# Review Brief: {self.target_kind}:{self.target_id}",
            "",
            "## Summary",
            "",
            self.summary,
            "",
            "## Key Decisions",
            "",
        ]
        if self.key_decisions:
            for decision in self.key_decisions:
                topic = decision.get("topic", "Decision")
                rationale = decision.get("rationale")
                line = f"- **{topic}**: {decision.get('decision', '')}"
                if rationale:
                    line += f" ({rationale})"
                lines.append(line)
        else:
            lines.append("- None recorded")
        lines.extend(["", "## Audit Findings", ""])
        if self.audit_findings:
            for finding in self.audit_findings:
                severity = str(finding.get("severity", "info")).upper()
                action = finding.get("suggested_action")
                line = f"- **{severity}**: {finding.get('message', '')}"
                if action:
                    line += f" Suggested action: {action}"
                lines.append(line)
        else:
            lines.append("- No significant findings")
        lines.extend(
            [
                "",
                "## Confidence Score",
                "",
                f"- Score: {self.confidence_score}",
            ]
        )
        if self.confidence_breakdown:
            for key, value in self.confidence_breakdown.items():
                lines.append(f"- {key}: {value}")
        lines.extend(["", "## Suggested Review Focus", ""])
        if self.suggested_focus:
            for item in self.suggested_focus:
                lines.append(f"- {item}")
        else:
            lines.append("- Review not required beyond standard checks")
        lines.extend(["", "## Reviewable Draft", ""])
        if self.rendered_preview_paths:
            lines.append("- Rendered Preview Paths:")
            for item in self.rendered_preview_paths:
                lines.append(f"  - `{item}`")
        else:
            lines.append("- No rendered previews recorded")
        lines.extend(["", "## Provenance Summary", ""])
        if self.provenance_summary:
            lines.append(f"- Imported Sections: {self.provenance_summary.get('imported', 0)}")
            lines.append(f"- Generated Sections: {self.provenance_summary.get('generated', 0)}")
            lines.append(f"- Authored Sections: {self.provenance_summary.get('authored', 0)}")
        else:
            lines.append("- No provenance summary recorded")
        if self.flagged_recommendations:
            lines.extend(["", "## Flagged Recommendations", ""])
            for item in self.flagged_recommendations:
                lines.append(f"- `{item}`")
        if self.clawspec_artifact_choices:
            lines.extend(["", "## ClawSpec Artifacts", ""])
            for artifact in self.clawspec_artifact_choices:
                default_action = artifact.get("default_action", "accept")
                lines.append(
                    f"- `{artifact.get('artifact', '')}` staged at `{artifact.get('staged_path', '')}` "
                    f"target `{artifact.get('final_path', '')}` default `{default_action}`"
                )
        if self.clawspec_delta_report:
            lines.extend(["", "## ClawSpec Coverage Delta", "", self.clawspec_delta_report.strip()])
        if self.clawspec_warnings:
            lines.extend(["", "## ClawSpec Warnings", ""])
            for warning in self.clawspec_warnings:
                lines.append(f"- {warning}")
        lines.extend(
            [
                "",
                "## Provenance",
                "",
                f"- Builder: {self.builder_identity}",
                f"- Mode: {self.mode}",
                f"- Transcript: {self.transcript_path}",
                f"- Created: {self.created_at}",
                "",
            ]
        )
        return "\n".join(lines)


@dataclass
class ReviewQueueEntry:
    target_key: str
    target_kind: str
    target_id: str
    mode: str
    builder_identity: str
    run_id: str
    confidence_score: float
    review_priority: str
    status: str
    review_brief_path: str
    transcript_path: str
    created_at: str
    reviewed_at: str | None = None
    reviewer: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewQueueEntry:
        return cls(
            target_key=data["target_key"],
            target_kind=data["target_kind"],
            target_id=data["target_id"],
            mode=data["mode"],
            builder_identity=data["builder_identity"],
            run_id=data["run_id"],
            confidence_score=float(data.get("confidence_score", 0.0)),
            review_priority=data.get("review_priority", "informational"),
            status=data.get("status", "pending"),
            review_brief_path=data["review_brief_path"],
            transcript_path=data["transcript_path"],
            created_at=data["created_at"],
            reviewed_at=data.get("reviewed_at"),
            reviewer=data.get("reviewer"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "target_key": self.target_key,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "mode": self.mode,
            "builder_identity": self.builder_identity,
            "run_id": self.run_id,
            "confidence_score": self.confidence_score,
            "review_priority": self.review_priority,
            "status": self.status,
            "review_brief_path": self.review_brief_path,
            "transcript_path": self.transcript_path,
            "created_at": self.created_at,
        }
        if self.reviewed_at:
            data["reviewed_at"] = self.reviewed_at
        if self.reviewer:
            data["reviewer"] = self.reviewer
        return data


@dataclass
class TargetSpec:
    kind: str
    id: str
    title: str
    description: str = ""
    tier: str | None = None
    tenant: str = "default"
    schema_version: str = "0.1.0"
    identity: dict[str, Any] = field(default_factory=dict)
    org: dict[str, Any] = field(default_factory=dict)
    operation: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    agent: dict[str, Any] | None = None
    skill: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetSpec:
        return cls(
            kind=data["kind"],
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            tier=data.get("tier"),
            tenant=data.get("tenant", "default"),
            schema_version=data.get("schema_version", "0.1.0"),
            identity=data.get("identity", {}),
            org=data.get("org", {}),
            operation=data.get("operation", {}),
            policy=data.get("policy", {}),
            provenance=data.get("provenance", {}),
            agent=data.get("agent"),
            skill=data.get("skill"),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tenant": self.tenant,
            "schema_version": self.schema_version,
            "identity": self.identity,
            "org": self.org,
            "operation": self.operation,
            "policy": self.policy,
            "provenance": self.provenance,
        }
        if self.tier:
            data["tier"] = self.tier
        if self.agent is not None:
            data["agent"] = self.agent
        if self.skill is not None:
            data["skill"] = self.skill
        return data


@dataclass
class ProfileSpec:
    id: str
    title: str
    category: str
    merge_priority: int
    applicability: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    merge_rules: dict[str, Any] = field(default_factory=dict)
    contributes: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileSpec:
        return cls(
            id=data["id"],
            title=data["title"],
            category=data["category"],
            merge_priority=int(data.get("merge_priority", 50)),
            applicability=data.get("applicability", {}),
            compatibility=data.get("compatibility", {}),
            merge_rules=data.get("merge_rules", {}),
            contributes=data.get("contributes", {}),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "merge_priority": self.merge_priority,
            "applicability": self.applicability,
            "compatibility": self.compatibility,
            "merge_rules": self.merge_rules,
            "contributes": self.contributes,
        }


@dataclass
class TenantSpec:
    name: str
    operator: dict[str, Any]
    notifications: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    config_policy: dict[str, Any] = field(default_factory=dict)
    cognition_registry: dict[str, Any] = field(default_factory=dict)
    subscription_tier: str = "pro"
    defaults: dict[str, Any] = field(default_factory=dict)
    boost: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantSpec:
        return cls(
            name=data["name"],
            operator=data["operator"],
            notifications=data.get("notifications", {}),
            compatibility=data.get("compatibility", {}),
            config_policy=data.get("config_policy", {}),
            cognition_registry=data.get("cognition_registry", {}),
            subscription_tier=data.get("subscription_tier", "pro"),
            defaults=data.get("defaults", {}),
            boost=data.get("boost", {}),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "operator": self.operator,
            "notifications": self.notifications,
            "compatibility": self.compatibility,
            "config_policy": self.config_policy,
            "cognition_registry": self.cognition_registry,
            "subscription_tier": self.subscription_tier,
            "defaults": self.defaults,
            "boost": self.boost,
        }


@dataclass
class ProposalEnvelope:
    action: str
    run_id: str
    proposer: str
    tenant: str
    created_at: str
    state: str
    payload: dict[str, Any]
    parent_run_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposalEnvelope:
        return cls(
            action=data["action"],
            run_id=data["run_id"],
            proposer=data["proposer"],
            tenant=data.get("tenant", "default"),
            created_at=data["created_at"],
            state=data["state"],
            payload=data["payload"],
            parent_run_id=data.get("parent_run_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "action": self.action,
            "run_id": self.run_id,
            "proposer": self.proposer,
            "tenant": self.tenant,
            "created_at": self.created_at,
            "state": self.state,
            "payload": self.payload,
        }
        if self.parent_run_id:
            data["parent_run_id"] = self.parent_run_id
        return data


@dataclass
class SanityConfig:
    """Sanity CMS configuration for a tenant site."""

    project_id: str = ""
    dataset: str = "production"
    api_version: str = "2024-01-01"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SanityConfig:
        return cls(
            project_id=data.get("project_id", ""),
            dataset=data.get("dataset", "production"),
            api_version=data.get("api_version", "2024-01-01"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "dataset": self.dataset,
            "api_version": self.api_version,
        }


@dataclass
class VercelConfig:
    """Vercel deployment configuration for a tenant site."""

    project: str = ""
    team: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VercelConfig:
        return cls(
            project=data.get("project", ""),
            team=data.get("team", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"project": self.project, "team": self.team}


@dataclass
class AnalyticsConfig:
    """Analytics configuration for a tenant site."""

    ga4_property: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalyticsConfig:
        return cls(ga4_property=data.get("ga4_property", ""))

    def to_dict(self) -> dict[str, Any]:
        return {"ga4_property": self.ga4_property}


@dataclass
class ContentSources:
    """Content source flags for a tenant site."""

    senja: bool = False
    airtable_retreats: bool = False
    chroma_corpus: str = ""
    campaign_api: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContentSources:
        return cls(
            senja=bool(data.get("senja", False)),
            airtable_retreats=bool(data.get("airtable_retreats", False)),
            chroma_corpus=data.get("chroma_corpus", ""),
            campaign_api=bool(data.get("campaign_api", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "senja": self.senja,
            "airtable_retreats": self.airtable_retreats,
            "chroma_corpus": self.chroma_corpus,
            "campaign_api": self.campaign_api,
        }


@dataclass
class TenantExtension:
    """Extension fields for a multi-website tenant target."""

    site_id: str = ""
    domain: str = ""
    brand_root: str = ""
    site_dir: str = ""
    sanity: SanityConfig = field(default_factory=SanityConfig)
    vercel: VercelConfig = field(default_factory=VercelConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)
    content_sources: ContentSources = field(default_factory=ContentSources)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantExtension:
        return cls(
            site_id=data.get("site_id", ""),
            domain=data.get("domain", ""),
            brand_root=data.get("brand_root", ""),
            site_dir=data.get("site_dir", ""),
            sanity=SanityConfig.from_dict(data.get("sanity") or {}),
            vercel=VercelConfig.from_dict(data.get("vercel") or {}),
            analytics=AnalyticsConfig.from_dict(data.get("analytics") or {}),
            content_sources=ContentSources.from_dict(data.get("content_sources") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "domain": self.domain,
            "brand_root": self.brand_root,
            "site_dir": self.site_dir,
            "sanity": self.sanity.to_dict(),
            "vercel": self.vercel.to_dict(),
            "analytics": self.analytics.to_dict(),
            "content_sources": self.content_sources.to_dict(),
        }


_BRAND_REQUIRED_FILES = [
    "brand-guide.md",
    "voice.md",
    "messaging.md",
    "content-system.md",
    "visual-direction.md",
    "tokens/design-system.yaml",
    "asset-checklist.md",
]

_BRAND_SOURCE_TYPES = {"imported", "generated", "authored"}


@dataclass
class BrandExtension:
    """Extension fields for a brand artifact target."""

    site_id: str = ""
    brand_name: str = ""
    required_files: list[str] = field(default_factory=lambda: list(_BRAND_REQUIRED_FILES))
    extra_files: list[str] = field(default_factory=list)
    source: str = "generated"
    source_ref: str = ""

    def __post_init__(self) -> None:
        _require_choice(self.source, _BRAND_SOURCE_TYPES, "source")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrandExtension:
        return cls(
            site_id=data.get("site_id", ""),
            brand_name=data.get("brand_name", ""),
            required_files=list(data.get("required_files", _BRAND_REQUIRED_FILES)),
            extra_files=list(data.get("extra_files", [])),
            source=data.get("source", "generated"),
            source_ref=data.get("source_ref", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "brand_name": self.brand_name,
            "required_files": list(self.required_files),
            "extra_files": list(self.extra_files),
            "source": self.source,
            "source_ref": self.source_ref,
        }


_SITE_STUDIO_MODES = {"embedded", "standalone"}

_SITE_SHARED_SCHEMAS = ["seo", "person", "socialLinks", "portableText"]


@dataclass
class SiteExtension:
    """Extension fields for a site scaffold target."""

    site_id: str = ""
    template: str = "sanity-nextjs-clean-app"
    tenant_ref: str = ""
    brand_ref: str = ""
    shared_schemas: list[str] = field(default_factory=lambda: list(_SITE_SHARED_SCHEMAS))
    custom_schemas: list[str] = field(default_factory=list)
    studio_mode: str = "embedded"

    def __post_init__(self) -> None:
        _require_choice(self.studio_mode, _SITE_STUDIO_MODES, "studio_mode")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SiteExtension:
        return cls(
            site_id=data.get("site_id", ""),
            template=data.get("template", "sanity-nextjs-clean-app"),
            tenant_ref=data.get("tenant_ref", ""),
            brand_ref=data.get("brand_ref", ""),
            shared_schemas=list(data.get("shared_schemas", _SITE_SHARED_SCHEMAS)),
            custom_schemas=list(data.get("custom_schemas", [])),
            studio_mode=data.get("studio_mode", "embedded"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "template": self.template,
            "tenant_ref": self.tenant_ref,
            "brand_ref": self.brand_ref,
            "shared_schemas": list(self.shared_schemas),
            "custom_schemas": list(self.custom_schemas),
            "studio_mode": self.studio_mode,
        }


@dataclass
class ResolvedManifest:
    target_id: str
    kind: str
    target: TargetSpec
    resolved: dict[str, Any]
    tenant: TenantSpec
    profiles: list[ProfileSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FileWriteEntry:
    generated_path: str
    runtime_path: str
    ownership_class: str
    content: str
    source: str = ""


@dataclass
class OutputManifest:
    target_id: str
    kind: str
    files: list[FileWriteEntry]
    config_ops: list[dict[str, Any]] = field(default_factory=list)
    rollback_info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "kind": self.kind,
            "files": [
                {
                    "generated_path": entry.generated_path,
                    "runtime_path": entry.runtime_path,
                    "ownership_class": entry.ownership_class,
                    "source": entry.source,
                }
                for entry in self.files
            ],
            "config_ops": self.config_ops,
            "rollback_info": self.rollback_info,
        }


@dataclass
class ReviewDecision:
    reviewer: str
    decision: str
    required: bool = True
    notes: str = ""


@dataclass
class NotificationEvent:
    run_id: str
    tier: str
    message: str
    channels: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunSummary:
    action: str
    run_id: str
    state: str
    target_ids: list[str]
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class CLIResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class ConfigCollision:
    key: str
    desired_value: Any
    live_value: Any
    mode: str
    resolution: str


@dataclass
class MigrationReport:
    runtime_path: str
    inferred_kind: str
    inferred_id: str
    extracted_fields: dict[str, Any]
    unmapped_sections: list[str] = field(default_factory=list)
    profile_matches: list[str] = field(default_factory=list)
    config_collisions: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class RunRecord:
    run_id: str
    run_dir: Path
