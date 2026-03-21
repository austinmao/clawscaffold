"""Deterministic planner core for the unified scaffold interview system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawscaffold.audit import build_audit_report
from clawscaffold.config_intelligence import (
    build_decision_bundles,
    detect_config_findings,
    detect_config_findings_pass1,
    detect_config_findings_pass2,
    merge_pass1_patches,
)
from clawscaffold.depth_mode import _check_hard_stops, evaluate_depth_mode
from clawscaffold.interview import (
    assemble_spec_from_interview,
    build_adopt_questions,
    create_interview_state,
    load_state_for_resume,
    process_answer,
)
from clawscaffold.manifests import build_output_manifest
from clawscaffold.models import (
    AuditReport,
    InterviewQuestion,
    InterviewState,
    ReviewableDraft,
    ReviewQueueEntry,
    SectionContent,
)
from clawscaffold.paths import repo_root
from clawscaffold.intent_signals import IntentSignalTracker
from clawscaffold.recommendations import (
    build_target_snapshot,
    compare_snapshot,
    provenance_summary,
    recommend_sections,
)
from clawscaffold.render import render_target
from clawscaffold.resolve import resolve_target
from clawscaffold.review import add_review_queue_entry, generate_review_brief
from clawscaffold.utils import (
    canonical_target_path,
    generated_target_dir,
    now_iso,
    write_json,
    write_text,
    write_yaml,
)


def _repo(root: Path | None = None) -> Path:
    return root or repo_root()


def _state_path(run_id: str, root: Path) -> Path:
    return root / "compiler" / "runs" / run_id / "interview.json"


def _save_state(state: InterviewState, root: Path) -> InterviewState:
    state.updated_at = now_iso()
    state.save(_state_path(state.run_id, root))
    return state


def _summary(state: InterviewState) -> dict[str, Any]:
    generated_count = sum(1 for recommendation in state.recommendations.values() if recommendation.source == "generated")
    flagged_count = sum(1 for recommendation in state.recommendations.values() if recommendation.review_required)
    return {
        "imported_sections": sum(1 for section in state.sections.values() if section.source == "imported"),
        "generated_sections": generated_count,
        "flagged_sections": flagged_count,
    }


def _question_payload(question: InterviewQuestion | None) -> dict[str, Any] | None:
    if question is None:
        return None
    payload = {
        "question_id": question.id,
        "question_type": question.question_type,
        "prompt_text": question.prompt_text,
        "choices": list(question.choices),
        "default_choice": question.recommended_choice,
        "recommendation_id": question.recommendation_id,
    }
    if question.extracted_value is not None:
        payload["extracted_value"] = question.extracted_value
    if question.full_text_visible and question.draft_content:
        payload["draft_content"] = question.draft_content
    if question.decision_bundle:
        payload["_026_decision_bundle"] = question.decision_bundle
    if question.structured_reason:
        payload["_026_structured_reason"] = question.structured_reason
    if question.provenance_basis:
        payload["_026_provenance_basis"] = question.provenance_basis
    if question.confidence_band:
        payload["_026_confidence_band"] = question.confidence_band
    if question.risk_level:
        payload["_026_risk_level"] = question.risk_level
    if question.blocking_level:
        payload["_026_blocking_level"] = question.blocking_level
    if question.batch_eligible:
        payload["_026_batch_eligible"] = True
    if question.tradeoff_note:
        payload["_026_tradeoff_note"] = question.tradeoff_note
    if question.hidden_assumption:
        payload["_026_hidden_assumption"] = question.hidden_assumption
    if question.question_type == "batch_confirm" and isinstance(question.extracted_value, dict):
        payload["_026_batched_question_ids"] = list(question.extracted_value.get("batched_question_ids", []))
    return payload


def _recommendation_questions(state: InterviewState) -> list[InterviewQuestion]:
    questions: list[InterviewQuestion] = []
    for recommendation in state.recommendations.values():
        if recommendation.status != "pending" or recommendation.recommendation_type != "missing_standard":
            continue
        questions.append(
            InterviewQuestion(
                id=f"recommendation.{recommendation.recommendation_id}",
                topic_group="recommendation",
                question_type="multiple_choice",
                prompt_text=f"I can add the missing section '{recommendation.heading}'. Accept, inspect, or skip?",
                choices=[
                    {"value": "accept", "label": "Accept", "description": "Use the recommended section as-is"},
                    {"value": "inspect", "label": "Inspect", "description": "Show the full generated text before deciding"},
                    {"value": "skip", "label": "Skip", "description": "Do not add this section"},
                ],
                recommended_choice="accept",
                draft_content=recommendation.content,
                recommendation_id=recommendation.recommendation_id,
                full_text_visible=recommendation.review_required,
            )
        )
    return questions


def _build_override_question(recommendation_id: str, state: InterviewState) -> InterviewQuestion | None:
    recommendation = state.recommendations.get(recommendation_id)
    if not recommendation or not recommendation.review_required:
        return None
    if recommendation.status != "accepted":
        return None
    return InterviewQuestion(
        id=f"override.{recommendation.recommendation_id}",
        topic_group="recommendation",
        question_type="override",
        prompt_text=f"Review or override the generated section '{recommendation.heading}'. Provide replacement content or keep the recommendation.",
        choices=[
            {"value": "keep", "label": "Keep", "description": "Keep the generated section"},
            {"value": "override", "label": "Override", "description": "Replace it with custom content"},
        ],
        recommended_choice="keep",
        draft_content=recommendation.content,
        recommendation_id=recommendation.recommendation_id,
        full_text_visible=True,
    )


def _recommendation_by_public_id(state: InterviewState, recommendation_id: str):
    for recommendation in state.recommendations.values():
        if recommendation.recommendation_id == recommendation_id:
            return recommendation
    return None


def _append_planner_questions(state: InterviewState) -> InterviewState:
    question_ids = {question.id for question in state.questions}
    for question in _recommendation_questions(state):
        if question.id not in question_ids:
            state.questions.append(question)
    if state.execution_style == "accept_recommendations":
        state.status = "ready_to_finalize"
    elif state.current_question_index < 0 and state.questions:
        state.current_question_index = 0
        state.status = "questioning"
    return state


def _refresh_recommendations(state: InterviewState, root: Path) -> InterviewState:
    state.recommendations = recommend_sections(state.target_kind, state.target_id, state.sections, state.policy_hints, root)
    if state.mode == "adopt":
        # Two-pass bundle execution: Pass 1 findings feed into Pass 2 via
        # merged default patches.  The combined wrapper already implements
        # this correctly, so we call detect_config_findings which internally
        # runs detect_config_findings_pass1 -> merge_pass1_patches ->
        # detect_config_findings_pass2 and returns the combined result.
        state.config_findings = detect_config_findings(state.target_kind, state.target_id, state.sections, state.policy_hints, root)
        state.decision_bundles = build_decision_bundles(state.config_findings, kind=state.target_kind, target_id=state.target_id)
        state.depth_mode = evaluate_depth_mode(state.config_findings, state.recommendations)
        state.questions = build_adopt_questions(state)
        state.current_question_index = 0 if state.questions else -1
        state.status = "questioning" if state.questions else "ready_to_finalize"
        return state
    return _append_planner_questions(state)


def analyze_run(
    *,
    mode: str,
    kind: str,
    target_id: str,
    execution_style: str = "interactive",
    root: Path | None = None,
    resume_run_id: str | None = None,
    builder_identity: str = "human:scaffold-cli",
    execution_env: str = "cli",
) -> tuple[InterviewState, dict[str, Any]]:
    base = _repo(root)
    if resume_run_id:
        state = load_state_for_resume(resume_run_id, base)
        state.execution_style = execution_style or state.execution_style
        snapshot = state.snapshot or build_target_snapshot(state.mode, state.target_kind, state.target_id, base)
        current = compare_snapshot(snapshot, base)
        if current.drift_state == "changed":
            state.snapshot = current
            resume_question = InterviewQuestion(
                id="resume.choice",
                topic_group="resume",
                question_type="multiple_choice",
                prompt_text="The target changed since this interview began. Continue with the current plan, refresh recommendations, or restart?",
                choices=[
                    {"value": "continue", "label": "Continue", "description": "Proceed with the current recommendations"},
                    {"value": "refresh", "label": "Refresh", "description": "Rebuild recommendations from current content"},
                    {"value": "restart", "label": "Restart", "description": "Reset the run from the current target state"},
                ],
                recommended_choice="refresh",
            )
            state.questions.insert(0, resume_question)
            state.current_question_index = 0
            state.status = "questioning"
        _save_state(state, base)
        return state, analyze_payload(state)

    state = create_interview_state(
        mode,
        kind,
        target_id,
        builder_identity,
        root=base,
        execution_env=execution_env,
    )
    state.execution_style = execution_style
    state.snapshot = build_target_snapshot(mode, kind, target_id, base)
    if mode in {"adopt", "extend"}:
        state = _refresh_recommendations(state, base)
    elif execution_style == "accept_recommendations":
        state.status = "ready_to_finalize"
    _save_state(state, base)
    return state, analyze_payload(state)


def analyze_payload(state: InterviewState) -> dict[str, Any]:
    safe_to_finalize = state.current_question_index < 0 or state.execution_style == "accept_recommendations"
    payload = {
        "run_id": state.run_id,
        "mode": state.mode,
        "execution_style": state.execution_style,
        "target": {"kind": state.target_kind, "id": state.target_id},
        "snapshot": state.snapshot.to_dict() if state.snapshot else None,
        "summary": _summary(state),
        "recommendations": [recommendation.to_dict() for recommendation in state.recommendations.values()],
        "safe_to_finalize": safe_to_finalize,
        "next_action": "finalize" if safe_to_finalize else "next_question",
    }
    if state.mode == "adopt":
        payload["_026_config_findings"] = [finding.to_dict() for finding in state.config_findings]
        payload["_026_depth_mode"] = state.depth_mode.to_dict() if state.depth_mode else None
        payload["_026_decision_bundles"] = [bundle.to_dict() for bundle in state.decision_bundles]
    return payload


def next_question(run_id: str, root: Path | None = None) -> dict[str, Any]:
    base = _repo(root)
    state = load_state_for_resume(run_id, base)
    question: InterviewQuestion | None = None
    if state.execution_style == "accept_recommendations" and state.reviewable_draft is None:
        question = None
    elif state.current_question_index >= 0:
        question = state.questions[state.current_question_index]
    elif state.reviewable_draft and state.execution_style == "accept_recommendations":
        flagged = next(
            (
                recommendation_id
                for recommendation_id, recommendation in state.recommendations.items()
                if recommendation.review_required and recommendation.status in {"accepted", "overridden"}
            ),
            None,
        )
        question = _build_override_question(flagged, state) if flagged else None
    return {"run_id": run_id, "question": _question_payload(question)}


def answer_question(
    run_id: str,
    question_id: str,
    *,
    choice: str | None = None,
    content: str | None = None,
    value_json: dict[str, Any] | None = None,
    root: Path | None = None,
) -> tuple[InterviewState, dict[str, Any]]:
    base = _repo(root)
    state = load_state_for_resume(run_id, base)

    if question_id.startswith("override."):
        recommendation_id = question_id.split(".", 1)[1]
        recommendation = _recommendation_by_public_id(state, recommendation_id)
        if recommendation is None:
            raise ValueError(f"Unknown recommendation: {recommendation_id}")
        if content:
            recommendation.status = "overridden"
            state.sections[recommendation.section_id] = SectionContent(
                id=recommendation.section_id,
                heading=recommendation.heading,
                content=content.strip(),
                source="authored",
                custom=recommendation.section_id not in {section.id for section in state.sections.values()},
                order=state.sections.get(recommendation.section_id).order if recommendation.section_id in state.sections else len(state.sections),
                content_hash=None,
            )
        else:
            recommendation.status = "accepted"
        state.reviewable_draft = None
        _save_state(state, base)
        return state, {"run_id": run_id, "status": state.status, "resolved_question_id": question_id, "next_action": "finalize"}

    question = next((item for item in state.questions if item.id == question_id), None)
    if question is None:
        raise ValueError(f"Unknown question: {question_id}")

    if question.id.startswith("section.") and value_json is None:
        if content is not None:
            value_json = {"action": "edit", "content": content}
        elif choice in {"keep", "accept"}:
            value_json = {"action": "keep", "content": str(question.extracted_value or question.draft_content or "")}
        elif choice == "edit":
            value_json = {"action": "edit", "content": str(question.extracted_value or question.draft_content or "")}

    if question.recommendation_id and choice == "inspect":
        question.full_text_visible = True
        question.draft_content = state.recommendations[question.recommendation_id].content
        _save_state(state, base)
        return state, {"run_id": run_id, "status": state.status, "resolved_question_id": question_id, "next_action": "next_question"}

    answer: Any = value_json if value_json is not None else choice
    if question.id.startswith("resume.choice"):
        selection = str(choice or "")
        if selection == "refresh":
            refreshed, _payload = analyze_run(
                mode=state.mode,
                kind=state.target_kind,
                target_id=state.target_id,
                execution_style=state.execution_style,
                root=base,
                builder_identity=state.builder_identity,
                execution_env=state.execution_env or "cli",
            )
            refreshed.run_id = state.run_id
            refreshed.created_at = state.created_at
            refreshed.updated_at = now_iso()
            _save_state(refreshed, base)
            return refreshed, {"run_id": run_id, "status": refreshed.status, "resolved_question_id": question_id, "next_action": "next_question"}
        if selection == "restart":
            restarted, _payload = analyze_run(
                mode=state.mode,
                kind=state.target_kind,
                target_id=state.target_id,
                execution_style=state.execution_style,
                root=base,
                builder_identity=state.builder_identity,
                execution_env=state.execution_env or "cli",
            )
            restarted.run_id = state.run_id
            restarted.created_at = state.created_at
            restarted.updated_at = now_iso()
            _save_state(restarted, base)
            return restarted, {"run_id": run_id, "status": restarted.status, "resolved_question_id": question_id, "next_action": "next_question"}
        answer = selection or "continue"

    state = process_answer(state, answer, root=base)
    if state.mode == "adopt":
        tracker = IntentSignalTracker(state.intent_signals)
        tracker.update(question.id, str(choice or answer or ""), answer)
        state.intent_signals = tracker.get_all_signals()
        if state.depth_mode and state.depth_mode.mode == "light":
            if question.decision_bundle and str(choice or answer or "") in {"review", "edit", "override"}:
                state.depth_mode = evaluate_depth_mode(state.config_findings, state.recommendations)
                hard_stops = list(state.depth_mode.hard_stop_triggers)
                hard_stops.append("mid_interview_escalation")
                state.depth_mode.hard_stop_triggers = hard_stops
                state.depth_mode.mode = "deep"
                state.depth_mode.transition_reason = "Switching to deep mode because the current answer surfaced a higher-consequence configuration decision."
            elif _check_hard_stops(state.config_findings, state.recommendations):
                state.depth_mode = evaluate_depth_mode(state.config_findings, state.recommendations)
        if state.current_question_index >= 0:
            rebuilt = build_adopt_questions(state)
            answered_ids = set(state.answers)
            if state.depth_mode and state.depth_mode.mode == "deep" and "mode.deep_announcement" in answered_ids:
                rebuilt = [item for item in rebuilt if item.id != "mode.deep_announcement"]
            state.questions = [item for item in rebuilt if item.id not in answered_ids]
            state.current_question_index = 0 if state.questions else -1
            if state.current_question_index < 0:
                state.status = "content_complete"
    _save_state(state, base)
    response = {
        "run_id": run_id,
        "status": state.status,
        "resolved_question_id": question_id,
        "decision_type": str(choice or "recorded"),
        "next_action": "finalize" if state.current_question_index < 0 else "next_question",
    }
    if state.mode == "adopt":
        response["_026_intent_signals"] = [signal.to_dict() for signal in state.intent_signals]
    return state, response


def _auto_accept(state: InterviewState, root: Path) -> InterviewState:
    while state.current_question_index >= 0:
        question = state.questions[state.current_question_index]
        if question.id == "resume.choice":
            raise ValueError("Cannot auto-finalize while a resume choice is unresolved.")
        if question.id.startswith("section."):
            answer = {"action": "keep", "content": str(question.extracted_value or question.draft_content or "")}
        elif question.recommendation_id:
            answer = "accept"
        else:
            answer = question.recommended_choice or ""
        state = process_answer(state, answer, root=root)
    return state


def _planner_audit(state: InterviewState, spec: dict[str, Any], base: Path) -> AuditReport:
    findings = []
    for recommendation in state.recommendations.values():
        if recommendation.review_required and recommendation.status in {"accepted", "overridden"}:
            findings.append(
                {
                    "severity": "warning" if "conflict" in recommendation.risk_flags else "info",
                    "message": f"Review generated section '{recommendation.heading}' before live apply.",
                    "suggested_action": "Inspect the rendered preview and review brief before apply.",
                    "section_id": recommendation.section_id,
                }
            )
    audit = build_audit_report(
        state.target_id,
        state.target_kind,
        state.mode,
        list(state.sections.values()),
        spec,
        base,
        behavioral=True,
        run_id=state.run_id,
    )
    audit.heuristic_findings.extend(findings)
    audit.compute_confidence()
    audit.review_priority = "recommended" if findings else "informational"
    return audit


def finalize_run(run_id: str, *, accept_recommendations: bool = False, root: Path | None = None) -> tuple[InterviewState, dict[str, Any]]:
    base = _repo(root)
    state = load_state_for_resume(run_id, base)
    if accept_recommendations or state.execution_style == "accept_recommendations":
        state = _auto_accept(state, base)
    elif state.current_question_index >= 0:
        raise ValueError("Cannot finalize while unresolved questions remain.")

    flagged = []
    for recommendation in state.recommendations.values():
        if recommendation.status == "pending":
            recommendation.status = "accepted"
        if recommendation.status in {"accepted", "overridden"} and recommendation.recommendation_type == "missing_standard":
            source = "generated" if recommendation.status == "accepted" else "authored"
            existing = state.sections.get(recommendation.section_id)
            state.sections[recommendation.section_id] = SectionContent(
                id=recommendation.section_id,
                heading=recommendation.heading,
                content=(existing.content if existing else recommendation.content).strip(),
                source=existing.source if existing else source,
                custom=existing.custom if existing else False,
                order=existing.order if existing else len(state.sections),
                content_hash=None,
            )
        if recommendation.review_required and recommendation.status in {"accepted", "overridden"}:
            flagged.append(recommendation.recommendation_id)

    spec = assemble_spec_from_interview(state, base)
    target_path = canonical_target_path(state.target_kind, state.target_id, base)
    write_yaml(target_path, spec)

    resolved = resolve_target(target_path)
    rendered = render_target(resolved, base / "compiler" / "templates")
    target_generated_dir = generated_target_dir(state.target_kind, state.target_id, base)
    preview_paths: list[str] = []
    for filename, content in rendered.items():
        path = target_generated_dir / filename
        write_text(path, content)
        preview_paths.append(str(path.relative_to(base)))
    manifest = build_output_manifest(resolved, rendered)
    write_json(base / "compiler" / "runs" / run_id / "manifest.json", {"run_id": run_id, "targets": [manifest.to_dict()]})

    draft = ReviewableDraft(
        run_id=run_id,
        target_kind=state.target_kind,
        target_id=state.target_id,
        canonical_spec_path=str(target_path.relative_to(base)),
        rendered_preview_paths=preview_paths,
        provenance_summary=provenance_summary(state.sections),
        flagged_recommendations=flagged,
        ready_for_apply=True,
        created_at=now_iso(),
    )
    state.reviewable_draft = draft
    audit = _planner_audit(state, spec, base)
    brief = generate_review_brief(state, audit, base)
    review_brief_path = base / "catalog" / f"{state.target_kind}s" / f"{state.target_id}.review.md"
    add_review_queue_entry(
        ReviewQueueEntry(
            target_key=f"{state.target_kind}:{state.target_id}",
            target_kind=state.target_kind,
            target_id=state.target_id,
            mode=state.mode,
            builder_identity=state.builder_identity,
            run_id=run_id,
            confidence_score=audit.confidence_score,
            review_priority=audit.review_priority,
            status="pending",
            review_brief_path=str(review_brief_path.relative_to(base)),
            transcript_path=brief.transcript_path,
            created_at=now_iso(),
        ),
        base,
    )
    write_json(
        base / "compiler" / "runs" / run_id / "reviewable-draft.json",
        {
            "run_id": run_id,
            "reviewable_draft": draft.to_dict(),
            "review_brief_path": str(review_brief_path.relative_to(base)),
            "audit": audit.to_dict(),
        },
    )
    state.status = "finalized"
    _save_state(state, base)
    return state, {
        "run_id": run_id,
        "status": "finalized",
        "reviewable_draft": draft.to_dict(),
        "review_brief_path": str(review_brief_path.relative_to(base)),
        "next_action": "render_validate_apply",
    }
