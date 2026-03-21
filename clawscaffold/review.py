"""Review decision helpers and interview review artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from clawscaffold.clawspec_delta import render_delta_markdown
from clawscaffold.clawspec_gen import iter_artifact_choices
from clawscaffold.models import AuditReport, InterviewState, ReviewBrief, ReviewDecision, ReviewQueueEntry
from clawscaffold.paths import repo_root
from clawscaffold.utils import now_iso, write_json, write_text

VALID_DECISIONS = {"approve", "approve_with_changes", "escalate", "reject"}


def required_quorum(target_id: str) -> int:
    if target_id.startswith("builder/") or "control-plane" in target_id:
        return 3
    return 1


def validate_review_decisions(target_id: str, decisions: Iterable[ReviewDecision]) -> bool:
    decisions = list(decisions)
    if len(decisions) < required_quorum(target_id):
        return False
    for decision in decisions:
        if decision.decision not in VALID_DECISIONS:
            raise ValueError(f"Unknown review decision: {decision.decision}")
    return True


def review_queue_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "compiler" / "review-queue.yaml"


def save_interview_transcript(state: InterviewState, root: Path | None = None) -> Path:
    base = root or repo_root()
    path = base / "catalog" / f"{state.target_kind}s" / f"{state.target_id}.interview.json"
    write_json(path, state.to_dict())
    return path


def generate_review_brief(state: InterviewState, audit: AuditReport, root: Path | None = None) -> ReviewBrief:
    base = root or repo_root()
    transcript_path = save_interview_transcript(state, base)
    structural_score = audit.structural_pass_rate * 100
    heuristic_score = 100 - (sum(1 for item in audit.heuristic_findings if item.get("severity") == "error") * 25)
    cross_score = (
        100
        if not audit.cross_references
        else round(sum(1 for item in audit.cross_references if item.get("resolved")) / len(audit.cross_references) * 100, 2)
    )
    behavioral_score = (
        100
        if not audit.behavioral_tests
        else round(sum(1 for item in audit.behavioral_tests if item.get("passed")) / len(audit.behavioral_tests) * 100, 2)
    )
    clawspec_score = None if audit.clawspec_valid is None else 100.0
    if audit.clawspec_valid is False:
        results = audit.clawspec_artifacts.validation_results if audit.clawspec_artifacts else []
        if results:
            valid = sum(1 for item in results if item.get("valid"))
            clawspec_score = round(valid / len(results) * 100, 2)
        else:
            clawspec_score = 0.0
    top_findings = audit.heuristic_findings[:3] or [
        {"severity": "info", "message": "No significant audit findings", "suggested_action": "Spot-check the generated files"}
    ]
    clawspec_delta_report = render_delta_markdown(audit.clawspec_delta) if audit.clawspec_delta else ""
    artifact_choices = iter_artifact_choices(audit.clawspec_artifacts, base) if audit.clawspec_artifacts is not None else []
    brief = ReviewBrief(
        target_id=state.target_id,
        target_kind=state.target_kind,
        mode=state.mode,
        builder_identity=state.builder_identity,
        summary=f"{state.mode.title()} flow completed for {state.target_kind}:{state.target_id}. Review the generated files and audit notes before promotion.",
        key_decisions=[
            {
                "topic": "Mode",
                "decision": state.mode,
                "rationale": f"Interview completed in execution environment `{state.execution_env or 'cli'}`",
            },
            {
                "topic": "Sections",
                "decision": f"{len(state.sections)} sections captured",
                "rationale": "Preserves imported or authored runtime content for later review",
            },
        ],
        audit_findings=top_findings,
        confidence_score=audit.confidence_score,
        confidence_breakdown={
            "structural": round(structural_score, 2),
            "heuristic": round(max(0.0, heuristic_score), 2),
            "cross_reference": cross_score,
            "behavioral": behavioral_score,
            "clawspec": clawspec_score,
        },
        suggested_focus=[
            finding.get("message", "")
            for finding in top_findings
            if finding.get("message")
        ][:3]
        or ["Review the rendered output for tone and completeness"],
        rendered_preview_paths=list(state.reviewable_draft.rendered_preview_paths) if state.reviewable_draft else [],
        provenance_summary=dict(state.reviewable_draft.provenance_summary) if state.reviewable_draft else {},
        flagged_recommendations=list(state.reviewable_draft.flagged_recommendations) if state.reviewable_draft else [],
        clawspec_artifact_choices=artifact_choices,
        clawspec_delta_report=clawspec_delta_report,
        clawspec_warnings=list(dict.fromkeys(audit.clawspec_warnings)),
        transcript_path=str(transcript_path.relative_to(base)),
        created_at=now_iso(),
    )
    if clawspec_score is None:
        brief.confidence_breakdown.pop("clawspec", None)
    brief_path = base / "catalog" / f"{state.target_kind}s" / f"{state.target_id}.review.md"
    write_text(brief_path, brief.render_markdown())
    return brief


def load_review_queue(root: Path | None = None) -> dict:
    path = review_queue_path(root)
    if not path.exists():
        return {"version": 1, "updated_at": None, "entries": {}}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("version", 1)
    data.setdefault("updated_at", None)
    data.setdefault("entries", {})
    return data


def save_review_queue(root: Path | None, queue: dict) -> Path:
    path = review_queue_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    queue["version"] = queue.get("version", 1)
    queue["updated_at"] = now_iso()
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(queue, handle, sort_keys=False, allow_unicode=False)
    return path


def add_review_queue_entry(entry: ReviewQueueEntry, root: Path | None = None) -> Path:
    queue = load_review_queue(root)
    queue.setdefault("entries", {})[entry.target_key] = entry.to_dict()
    return save_review_queue(root, queue)


def list_review_entries(root: Path | None = None) -> list[ReviewQueueEntry]:
    queue = load_review_queue(root)
    priority_rank = {"mandatory": 0, "recommended": 1, "informational": 2}
    entries = [ReviewQueueEntry.from_dict({"target_key": key, **value}) for key, value in queue.get("entries", {}).items()]
    return sorted(entries, key=lambda entry: (priority_rank.get(entry.review_priority, 9), entry.created_at), reverse=False)


def update_review_entry(target_key: str, status: str, reviewer: str, root: Path | None = None) -> Path:
    queue = load_review_queue(root)
    entry = queue.get("entries", {}).get(target_key)
    if entry is None:
        raise KeyError(f"Review queue entry not found: {target_key}")
    entry["status"] = status
    entry["reviewed_at"] = now_iso()
    entry["reviewer"] = reviewer
    return save_review_queue(root, queue)
