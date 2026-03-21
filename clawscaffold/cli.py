"""CLI entrypoint for the spec-first scaffolder."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

from clawscaffold.adopt import (
    adoption_registry_path,
    build_backfilled_spec,
    find_adoption_entry,
    generate_draft_spec,
    generate_migration_report,
    infer_target_from_runtime_path,
    promote_to_managed,
    record_adoption_event,
    sync_adoption_inventory,
)
from clawscaffold.audit import assess_migration_readiness, build_audit_report
from clawscaffold.clawspec_bridge import register_coverage
from clawscaffold.clawspec_gen import generate_ledger_entry
from clawscaffold.config_apply import apply_config_ops, verify_visibility
from clawscaffold.constants import REQUIRED_SOUL_SECTIONS, SKILL_FRONTMATTER_REQUIRED
from clawscaffold.content_loss import (
    compute_content_loss_preview,
    preview_runtime_content,
    should_enforce_content_loss,
)
from clawscaffold.docs import write_generated_doc_artifacts
from clawscaffold.enforcement import generate_managed_registry
from clawscaffold.enforcement import registry_path as managed_registry_path
from clawscaffold.interview import (
    append_policy_pass,
    apply_org_chart_answers,
    assemble_spec_from_interview,
    auto_apply_pipeline,
    build_default_agent_spec,
    build_default_brand_spec,
    build_default_site_spec,
    build_default_skill_spec,
    build_default_tenant_spec,
    build_org_chart_interview,
    create_interview_state,
    draft_section_content,
    load_state_for_resume,
    process_answer,
    runtime_file_for_target,
    runtime_hash_for_state,
)
from clawscaffold.manifests import build_output_manifest
from clawscaffold.models import ClawSpecDecisions, InterviewState, NotificationEvent, ReviewQueueEntry
from clawscaffold.notifications import classify_notification_tier, deliver_notification
from clawscaffold.ownership import build_config_ops
from clawscaffold.paths import default_tenant_name, repo_root
from clawscaffold.planner import analyze_run, finalize_run
from clawscaffold.planner import answer_question as planner_answer_question
from clawscaffold.planner import next_question as planner_next_question
from clawscaffold.proposals import create_proposal, write_proposal
from clawscaffold.qa import check_runner_configured, render_qa_outputs
from clawscaffold.render import render_target
from clawscaffold.resolve import resolve_target
from clawscaffold.review import (
    add_review_queue_entry,
    generate_review_brief,
    list_review_entries,
    update_review_entry,
)
from clawscaffold.rollback import create_snapshot, rollback_run
from clawscaffold.run_state import RunStateMachine
from clawscaffold.section_parser import infer_policy_hints, parse_sections, parse_skill_sections
from clawscaffold.utils import (
    canonical_target_path,
    ensure_dir,
    generated_target_dir,
    iter_target_paths,
    now_iso,
    read_json,
    read_yaml,
    sha256_prefix,
    write_json,
    write_text,
    write_yaml,
)
from clawscaffold.validation import SchemaValidationError, validate_dict


def _repo() -> Path:
    return repo_root()


def _run_dir(action: str) -> tuple[str, Path]:
    run_id = __import__("clawscaffold.utils", fromlist=["run_id"]).run_id(action)
    run_dir = _repo() / "compiler" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def _write_summary(run_id: str, action: str, state: str, target_ids: list[str], artifacts: dict[str, Any]) -> Path:
    path = _repo() / "compiler" / "runs" / run_id / "summary.json"
    write_json(path, {"run_id": run_id, "action": action, "state": state, "target_ids": target_ids, "artifacts": artifacts})
    return path


def _write_log(run_id: str, action: str, lines: list[str]) -> Path:
    log_path = _repo() / "memory" / "logs" / "scaffold" / f"{now_iso()[:10]}-{run_id}.md"
    write_text(log_path, "\n".join([f"# {action} {run_id}", "", *lines, ""]))
    return log_path


def _load_target_path(target_id: str) -> tuple[str, Path]:
    agent_path = canonical_target_path("agent", target_id, _repo())
    if agent_path.exists():
        return "agent", agent_path
    skill_path = canonical_target_path("skill", target_id, _repo())
    if skill_path.exists():
        return "skill", skill_path
    tenant_path = canonical_target_path("tenant", target_id, _repo())
    if tenant_path.exists():
        return "tenant", tenant_path
    brand_path = canonical_target_path("brand", target_id, _repo())
    if brand_path.exists():
        return "brand", brand_path
    site_path = canonical_target_path("site", target_id, _repo())
    if site_path.exists():
        return "site", site_path
    raise FileNotFoundError(f"Target not found in catalog: {target_id}")


def _kind_from_catalog_path(path: Path) -> str:
    path_str = str(path)
    if "catalog/agents" in path_str:
        return "agent"
    if "catalog/tenants" in path_str:
        return "tenant"
    if "catalog/brands" in path_str:
        return "brand"
    if "catalog/sites" in path_str:
        return "site"
    return "skill"


def _selected_targets(args: Namespace) -> list[str]:
    if getattr(args, "all", False):
        target_ids = []
        for path in iter_target_paths(_repo()):
            kind = _kind_from_catalog_path(path)
            prefix = f"catalog/{kind}s/"
            target_ids.append(str(path.relative_to(_repo() / prefix)).replace(".yaml", ""))
        return target_ids
    return [args.id]


def _render_one(target_id: str, run_dir: Path) -> dict[str, Any]:
    kind, target_path = _load_target_path(target_id)
    resolved = resolve_target(target_path)
    rendered = render_target(resolved, _repo() / "compiler" / "templates")
    manifest = build_output_manifest(resolved, rendered)

    resolved_path = _repo() / "compiler" / "generated" / "resolved" / f"{target_id}.yaml"
    write_yaml(resolved_path, resolved.resolved)
    target_generated_dir = generated_target_dir(kind, target_id, _repo())
    for filename, content in rendered.items():
        write_text(target_generated_dir / filename, content)
    write_generated_doc_artifacts(resolved, _repo())
    return {"resolved": resolved, "rendered": rendered, "manifest": manifest}


def _validate_file_content(target_id: str, kind: str, filename: str, content: str) -> list[str]:
    errors = []
    if kind == "agent" and filename == "SOUL.md":
        for section in REQUIRED_SOUL_SECTIONS:
            if f"# {section}" not in content:
                errors.append(f"Missing required section: # {section}")
    if kind == "skill" and filename == "SKILL.md":
        if not content.startswith("---\n"):
            errors.append("Missing YAML frontmatter")
        for key in SKILL_FRONTMATTER_REQUIRED:
            if f"{key}:" not in content:
                errors.append(f"Missing frontmatter key: {key}")
    if "<!-- oc:section" not in content:
        errors.append("Missing generated section markers")
    return errors


def _validate_rendered(target_id: str) -> dict[str, Any]:
    kind, _ = _load_target_path(target_id)
    target_dir = generated_target_dir(kind, target_id, _repo())
    report = {"target_id": target_id, "kind": kind, "errors": [], "warnings": []}
    for file_path in sorted(target_dir.glob("*.md")):
        content = file_path.read_text(encoding="utf-8")
        report["errors"].extend(_validate_file_content(target_id, kind, file_path.name, content))
    return report


def _prompt(label: str) -> str:
    print(label, end=" ", flush=True)
    try:
        return input().strip()
    except EOFError:
        return ""


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _audit_payload(audit: Any) -> dict[str, Any]:
    return audit.to_dict() if hasattr(audit, "to_dict") else dict(audit or {})


def _merge_scenario_documents(existing_path: Path, staged_path: Path) -> None:
    existing = read_yaml(existing_path) if existing_path.exists() else {}
    generated = read_yaml(staged_path)
    existing_scenarios = {
        scenario.get("name") or scenario.get("id"): scenario
        for scenario in existing.get("scenarios", [])
        if isinstance(scenario, dict)
    }
    for scenario in generated.get("scenarios", []):
        if not isinstance(scenario, dict):
            continue
        existing_scenarios[scenario.get("name") or scenario.get("id")] = scenario
    merged = dict(existing)
    for key in ("version", "target", "defaults"):
        if key in generated:
            merged[key] = generated[key]
    merged["scenarios"] = list(existing_scenarios.values())
    write_yaml(existing_path, merged)


def _apply_clawspec_artifacts(audit: Any, run_id: str, *, kind: str, target_id: str) -> Path | None:
    payload = _audit_payload(audit)
    artifacts = payload.get("clawspec_artifacts") or {}
    if not artifacts:
        return None

    staging_dir = Path(artifacts.get("staging_dir", ""))
    if not staging_dir.exists():
        return None

    target_tests_dir = runtime_file_for_target(kind, target_id, _repo()).parent / "tests"
    entries: list[tuple[str, Path, Path | None]] = []
    scenarios_staged = staging_dir / "scenarios.yaml"
    if scenarios_staged.exists():
        entries.append(("scenarios.yaml", scenarios_staged, target_tests_dir / "scenarios.yaml"))

    for name in sorted((artifacts.get("handoff_contracts") or {}).keys()):
        staged = staging_dir / "handoffs" / name
        if staged.exists():
            entries.append((f"handoffs/{name}", staged, target_tests_dir / "handoffs" / name))

    pipeline_staged = staging_dir / "pipeline.yaml"
    if pipeline_staged.exists():
        entries.append(("pipeline.yaml", pipeline_staged, target_tests_dir / "pipeline.yaml"))
    ledger_staged = staging_dir / "ledger-entry.yaml"
    if ledger_staged.exists():
        entries.append(("ledger-entry.yaml", ledger_staged, None))

    decisions: dict[str, str] = {}
    for display_name, staged_path, final_path in entries:
        default_action = "merge" if final_path is not None and final_path.exists() else "accept"
        answer = (_prompt(f"ClawSpec {display_name} [A]ccept / [m]erge / [s]kip?") or default_action[:1]).lower()
        if answer.startswith("s"):
            decisions[display_name] = "skip"
            continue
        if answer.startswith("m"):
            decisions[display_name] = "merge"
            if final_path is None:
                continue
            ensure_dir(final_path.parent)
            if display_name == "scenarios.yaml" and final_path.exists():
                _merge_scenario_documents(final_path, staged_path)
            elif final_path.exists():
                # Non-scenario merge keeps the existing artifact in place.
                pass
            else:
                write_text(final_path, staged_path.read_text(encoding="utf-8"))
            continue
        decisions[display_name] = "accept"
        if final_path is None:
            continue
        ensure_dir(final_path.parent)
        write_text(final_path, staged_path.read_text(encoding="utf-8"))

    decisions_path = _repo() / "compiler" / "runs" / run_id / "clawspec-decisions.json"
    write_json(
        decisions_path,
        ClawSpecDecisions(run_id=run_id, target_id=target_id, decisions=decisions, decided_at=now_iso()).to_dict(),
    )

    applied_scenarios = read_yaml(target_tests_dir / "scenarios.yaml") if (target_tests_dir / "scenarios.yaml").exists() else None
    applied_handoffs: dict[str, Any] = {}
    handoff_dir = target_tests_dir / "handoffs"
    if handoff_dir.exists():
        for path in sorted(handoff_dir.glob("*.yaml")):
            applied_handoffs[path.name] = read_yaml(path)
    applied_pipeline = read_yaml(target_tests_dir / "pipeline.yaml") if (target_tests_dir / "pipeline.yaml").exists() else None

    warnings = list(payload.get("clawspec_warnings", []))
    skipped = sorted(name for name, action in decisions.items() if action == "skip")
    if skipped:
        warnings.append(f"Deferred artifacts: {', '.join(skipped)}")
    ledger_entry = generate_ledger_entry(
        target_id=target_id,
        kind=kind,
        tier=(artifacts.get("target_tier") or "interior-skill"),
        scenarios=applied_scenarios or {},
        handoff_contracts=applied_handoffs,
        pipeline=applied_pipeline,
        decisions=decisions,
        warnings=warnings,
    )
    write_yaml(target_tests_dir / "ledger-entry.yaml", ledger_entry)
    register_result = register_coverage(ledger_entry)
    warning = register_result.get("warning") if isinstance(register_result, dict) else None
    if warning:
        print(f"[scaffold clawspec] warning: {warning}")
    return decisions_path


_RUNTIME_DIR_TO_KIND: dict[str, str] = {
    "agents": "agent",
    "skills": "skill",
    "tenants": "tenant",
    "brands": "brand",
    "sites": "site",
}


def _infer_context_target() -> tuple[str, str] | None:
    cwd = Path.cwd().resolve()
    repo = _repo().resolve()
    try:
        relative = cwd.relative_to(repo)
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) >= 2 and parts[0] in _RUNTIME_DIR_TO_KIND:
        kind = _RUNTIME_DIR_TO_KIND[parts[0]]
        return kind, "/".join(parts[1:])
    return None


def _infer_kind(target_id: str | None, explicit_kind: str | None = None) -> str | None:
    if explicit_kind:
        return explicit_kind
    if not target_id:
        return None
    try:
        return _load_target_path(target_id)[0]
    except FileNotFoundError:
        for kind in ("agent", "skill", "tenant", "brand", "site"):
            if runtime_file_for_target(kind, target_id, _repo()).exists():
                return kind
    return None


def _load_runtime_sections(kind: str, target_id: str) -> list:
    runtime_path = runtime_file_for_target(kind, target_id, _repo())
    if not runtime_path.exists():
        return []
    text = runtime_path.read_text(encoding="utf-8")
    if kind == "agent":
        return parse_sections(text)
    if kind in {"tenant", "brand", "site"}:
        return []
    _frontmatter, sections = parse_skill_sections(text)
    return sections


def _persist_interview_spec(state: InterviewState, run_dir: Path) -> Path:
    from clawscaffold.governance import build_default_governance_record, write_governance_manifest

    spec = assemble_spec_from_interview(state, _repo())
    target_path = canonical_target_path(state.target_kind, state.target_id, _repo())
    write_yaml(target_path, spec)
    _render_one(state.target_id, run_dir)

    # Write governance manifest alongside catalog
    try:
        tenant = spec.get("tenant", "ceremonia")
        gov_record = build_default_governance_record(state.target_kind, state.target_id, tenant)
        write_governance_manifest(gov_record, _repo())
    except Exception:
        pass

    return target_path


def _prompt_draft_acceptance(question: Any, state: InterviewState) -> dict[str, str]:
    section_id = question.id.split(".", 1)[1]
    current_content = question.extracted_value if isinstance(question.extracted_value, str) else None
    draft = draft_section_content(
        state.target_kind,
        section_id,
        state.answers,
        root=_repo(),
        current_content=current_content,
    )
    print(draft)
    action = (_prompt("[A]ccept / [e]dit / [r]egenerate?") or "a").lower()
    if action.startswith("e"):
        edited = _prompt("Edited content:")
        return {"action": "edit", "content": edited or draft}
    if action.startswith("r"):
        regenerated = draft_section_content(
            state.target_kind,
            section_id,
            state.answers,
            root=_repo(),
            regenerate=True,
            current_content=current_content or draft,
        )
        print(regenerated)
        action = (_prompt("[A]ccept regenerated / [e]dit?") or "a").lower()
        if action.startswith("e"):
            edited = _prompt("Edited content:")
            return {"action": "edit", "content": edited or regenerated}
        return {"action": "regenerate", "content": regenerated}
    return {"action": "accept", "content": draft}


def _print_planner_summary(payload: dict[str, Any]) -> None:
    summary = payload.get("summary", {})
    target = payload.get("target", {})
    print(
        "[scaffold interview] "
        f"{target.get('kind', 'target')}:{target.get('id', '')} "
        f"imported={summary.get('imported_sections', 0)} "
        f"generated={summary.get('generated_sections', 0)} "
        f"flagged={summary.get('flagged_sections', 0)}"
    )


def _run_adopt_planner_shell(state: InterviewState, payload: dict[str, Any]) -> int:
    _print_planner_summary(payload)
    keep_all = (_prompt("Keep imported standard sections as-is? [Y/n]") or "y").lower()
    if keep_all not in {"n", "no"}:
        while True:
            current = load_state_for_resume(state.run_id, _repo())
            question = planner_next_question(state.run_id, _repo()).get("question")
            if not question or not question["question_id"].startswith("section."):
                break
            section_id = question["question_id"].split(".", 1)[1]
            section = current.sections.get(section_id)
            if not section or section.custom:
                break
            planner_answer_question(
                state.run_id,
                question["question_id"],
                value_json={"action": "keep", "content": str(question.get("extracted_value", ""))},
                root=_repo(),
            )

    while True:
        question = planner_next_question(state.run_id, _repo()).get("question")
        if not question:
            break

        print(f"[scaffold interview] {question['prompt_text']}")
        if question.get("draft_content"):
            print(question["draft_content"])

        if question["question_id"].startswith("section."):
            current_text = str(question.get("extracted_value", ""))
            if current_text:
                print(current_text)
            choice = (_prompt("[K]eep / [e]dit?") or "k").lower()
            if choice.startswith("e"):
                edited = _prompt("Edited content:")
                answer_payload = {"action": "edit", "content": edited or current_text}
            else:
                answer_payload = {"action": "keep", "content": current_text}
            planner_answer_question(
                state.run_id,
                question["question_id"],
                value_json=answer_payload,
                root=_repo(),
            )
            continue

        if question["question_id"].startswith("recommendation.") or question["question_id"] == "resume.choice":
            for choice in question.get("choices", []):
                marker = " (recommended)" if choice["value"] == question.get("default_choice") else ""
                print(f"  - {choice['value']}: {choice['description']}{marker}")
            answer = _prompt(">") or question.get("default_choice") or ""
            planner_answer_question(
                state.run_id,
                question["question_id"],
                choice=answer,
                root=_repo(),
            )
            continue

        answer = _prompt(">") or question.get("default_choice") or ""
        planner_answer_question(
            state.run_id,
            question["question_id"],
            choice=answer,
            root=_repo(),
        )

    state = load_state_for_resume(state.run_id, _repo())
    if not any(question.id.startswith("policy.") for question in state.questions):
        tune = (_prompt("Want to tune policy settings? [y/N]") or "n").lower()
        if tune in {"y", "yes"}:
            state = append_policy_pass(state, root=_repo())
            while state.current_question_index >= 0:
                question = state.questions[state.current_question_index]
                print(f"[scaffold interview] {question.prompt_text}")
                if question.question_type == "multiple_choice":
                    for choice in question.choices:
                        marker = " (recommended)" if choice["value"] == question.recommended_choice else ""
                        print(f"  - {choice['value']}: {choice['description']}{marker}")
                    answer = _prompt(">") or question.recommended_choice or ""
                    state = process_answer(state, answer, root=_repo())
                    continue
                if question.question_type == "gap_fill":
                    if question.extracted_value:
                        print(question.extracted_value)
                    answer = _prompt(">") or str(question.extracted_value or "")
                    state = process_answer(state, answer, root=_repo())
                    continue

    _state, finalized = finalize_run(state.run_id, root=_repo())
    draft = finalized["reviewable_draft"]
    reviewable_payload = read_json(_repo() / "compiler" / "runs" / state.run_id / "reviewable-draft.json")
    audit_payload = reviewable_payload.get("audit", {})
    decisions_path = _apply_clawspec_artifacts(audit_payload, state.run_id, kind=state.target_kind, target_id=state.target_id)
    print(f"[scaffold interview] run-id: {state.run_id}")
    print(f"[scaffold interview] spec: {_repo() / draft['canonical_spec_path']}")
    if finalized.get("review_brief_path"):
        print(f"[scaffold interview] review: {_repo() / finalized['review_brief_path']}")
    if draft.get("rendered_preview_paths"):
        print(f"[scaffold interview] rendered: {_repo() / draft['rendered_preview_paths'][0]}")
    if decisions_path:
        print(f"[scaffold interview] clawspec decisions: {decisions_path}")
    return 0


def handle_create(args: Namespace) -> int:
    from clawscaffold.governance import build_default_governance_record, write_governance_manifest

    tenant = args.tenant or default_tenant_name(_repo())
    if args.kind == "agent":
        spec = build_default_agent_spec(args.id, tenant)
    elif args.kind == "tenant":
        spec = build_default_tenant_spec(args.id, tenant)
    elif args.kind == "brand":
        spec = build_default_brand_spec(args.id, tenant)
    elif args.kind == "site":
        spec = build_default_site_spec(args.id, tenant)
    else:
        spec = build_default_skill_spec(args.id, tenant)

    run_id, run_dir = _run_dir("create")
    target_path = canonical_target_path(args.kind, args.id, _repo())
    proposal = create_proposal(
        action="create",
        target_id=args.id,
        proposer="human:scaffold-cli",
        tenant=tenant,
        payload={"kind": args.kind, "id": args.id, "initial_fields": spec, "interview_used": not args.non_interactive},
    )
    write_yaml(target_path, spec)

    # Write governance manifest alongside catalog
    try:
        gov_record = build_default_governance_record(args.kind, args.id, tenant)
        write_governance_manifest(gov_record, _repo())
    except Exception:
        pass  # Non-fatal
    proposal = proposal.__class__(**{**proposal.to_dict(), "run_id": run_id})
    write_proposal(proposal, run_dir)
    summary_path = _write_summary(run_id, "create", "proposed", [args.id], {"spec_path": str(target_path)})
    _write_log(run_id, "create", [f"- Spec: `{target_path}`", f"- Proposal: `{run_dir / 'proposal.json'}`", f"- Summary: `{summary_path}`"])
    print(f"[scaffold create] run-id: {run_id}")
    print(f"[scaffold create] Writing canonical spec: {target_path}")
    return 0


def handle_interview_agent_analyze(args: Namespace) -> int:
    if args.resume:
        _state, payload = analyze_run(
            mode=args.mode or "adopt",
            kind=args.kind or "agent",
            target_id=args.id or "",
            execution_style=args.execution_style,
            root=_repo(),
            resume_run_id=args.resume,
        )
    else:
        if not args.mode or not args.kind or not args.id:
            print("[scaffold interview-agent analyze] --mode, --kind, and --id are required unless --resume is used", file=sys.stderr)
            return 1
        _state, payload = analyze_run(
            mode=args.mode,
            kind=args.kind,
            target_id=args.id,
            execution_style=args.execution_style,
            root=_repo(),
        )
    _print_json(payload)
    return 0


def handle_interview_agent_next_question(args: Namespace) -> int:
    _print_json(planner_next_question(args.run_id, _repo()))
    return 0


def handle_interview_agent_answer(args: Namespace) -> int:
    content = None
    value_json = None
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    if args.value_json:
        value_json = json.loads(args.value_json)
    _state, payload = planner_answer_question(
        args.run_id,
        args.question_id,
        choice=args.choice,
        content=content,
        value_json=value_json,
        root=_repo(),
    )
    _print_json(payload)
    return 0


def handle_interview_agent_finalize(args: Namespace) -> int:
    _state, payload = finalize_run(args.run_id, accept_recommendations=args.accept_recommendations, root=_repo())
    _print_json(payload)
    return 0


def handle_render(args: Namespace) -> int:
    run_id, run_dir = _run_dir("render")
    manifests = []
    for target_id in _selected_targets(args):
        rendered = _render_one(target_id, run_dir)
        manifests.append(rendered["manifest"])
    manifest_path = run_dir / "manifest.json"
    write_json(manifest_path, {"run_id": run_id, "targets": [item.to_dict() for item in manifests]})
    _write_summary(run_id, "render", "rendered", [item.target_id for item in manifests], {"manifest": str(manifest_path)})
    print(f"[scaffold render] run-id: {run_id}")
    print(f"[scaffold render] Manifest: {manifest_path}")
    return 0


def handle_validate(args: Namespace) -> int:
    run_id, run_dir = _run_dir("validate")
    reports = [_validate_rendered(target_id) for target_id in _selected_targets(args)]
    path = run_dir / "validation-report.json"
    write_json(path, {"run_id": run_id, "reports": reports})
    error_count = sum(len(report["errors"]) for report in reports)
    _write_summary(run_id, "validate", "validated" if error_count == 0 else "blocked", _selected_targets(args), {"validation_report": str(path)})
    print(f"[scaffold validate] run-id: {run_id}")
    print(f"[scaffold validate] Errors: {error_count}")
    return 0 if error_count == 0 else 1


def handle_apply(args: Namespace) -> int:
    target_ids = _selected_targets(args)
    run_id, run_dir = _run_dir("apply")
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    manifests = []
    all_runtime_paths = []
    content_loss_reports = []
    planned_writes: list[tuple[Any, str]] = []
    blocking_reports: list[tuple[Any, Any]] = []
    for target_id in target_ids:
        validation = _validate_rendered(target_id)
        if validation["errors"]:
            print(f"[scaffold apply] validation failed for {target_id}: {validation['errors']}", file=sys.stderr)
            return 1
        kind, _ = _load_target_path(target_id)
        rendered_dir = generated_target_dir(kind, target_id, _repo())
        resolved = resolve_target(canonical_target_path(kind, target_id, _repo()))
        rendered_files = {path.name: path.read_text(encoding="utf-8") for path in rendered_dir.glob("*.md")}
        manifest = build_output_manifest(resolved, rendered_files)
        manifests.append(manifest)
        all_runtime_paths.extend(Path(entry.runtime_path) for entry in manifest.files)
        for entry in manifest.files:
            runtime_path = Path(entry.runtime_path)
            planned_content = preview_runtime_content(entry, runtime_path)
            planned_writes.append((entry, planned_content))
            report = compute_content_loss_preview(runtime_path, planned_content, Path(entry.generated_path))
            content_loss_reports.append(report)
            if runtime_path.exists() and should_enforce_content_loss(entry) and not report.passed:
                blocking_reports.append((entry, report))

    if dry_run:
        print(f"[scaffold apply --dry-run] Apply plan for {', '.join(target_ids)}")
        for manifest in manifests:
            for entry in manifest.files:
                print(f"{entry.runtime_path} ({entry.ownership_class})")
        for report in content_loss_reports:
            if report.live_line_count == 0:
                continue
            print(
                f"[scaffold apply --dry-run] Content preservation: {report.preservation_pct}% "
                f"({report.preserved_line_count}/{report.live_line_count}) for {report.live_path}"
            )
        for entry, report in blocking_reports:
            print(
                f"[scaffold apply --dry-run] WOULD BLOCK: {entry.runtime_path} "
                f"at {report.preservation_pct}% ({report.preserved_line_count}/{report.live_line_count})"
            )
        return 0

    if blocking_reports and not force:
        entry, report = blocking_reports[0]
        print(
            f"[scaffold apply] blocked by content preservation gate for {entry.runtime_path}: "
            f"{report.preservation_pct}% preserved ({report.preserved_line_count}/{report.live_line_count})",
            file=sys.stderr,
        )
        return 1

    state = RunStateMachine(run_id=run_id, lock_path=_repo() / "compiler" / ".lock")
    state.acquire_lock()
    try:
        state.transition("drafted")
        state.transition("reviewed")
        state.transition("approved_for_apply")
        state.transition("rendered")
        state.transition("validated")
        config_ops = []
        for manifest in manifests:
            config_ops.extend(
                build_config_ops({}, {}, resolve_target(canonical_target_path(manifest.kind, manifest.target_id, _repo())).tenant.config_policy)
            )
        snapshots = create_snapshot(run_dir, [*all_runtime_paths, managed_registry_path(_repo())])
        rollback_path = run_dir / "rollback.json"
        write_json(rollback_path, {"run_id": run_id, "files": snapshots, "config_ops": config_ops})
        for _entry, report in blocking_reports:
            if report.live_line_count and not report.passed and force:
                print(
                    f"[scaffold apply] warning: forcing apply despite {report.preservation_pct}% preservation for {report.live_path}",
                    file=sys.stderr,
                )
        for entry, planned_content in planned_writes:
            write_text(Path(entry.runtime_path), planned_content)
        apply_config_ops(config_ops)
        state.transition("applied")
        for manifest in manifests:
            if not verify_visibility(manifest.target_id, manifest.kind, _repo()):
                state.transition("rollback_pending")
                raise RuntimeError(f"Visibility check failed for {manifest.target_id}")
        state.transition("refreshed")
        state.transition("qa_passed")
        state.transition("completed")
        managed_registry = generate_managed_registry(manifests, _repo())
        summary_path = _write_summary(
            run_id,
            "apply",
            state.state,
            target_ids,
            {
                "rollback": str(rollback_path),
                "state": state.to_dict(),
                "managed_registry": str(managed_registry),
                "content_loss": [report.to_dict() for report in content_loss_reports],
            },
        )
        event = NotificationEvent(run_id=run_id, tier=classify_notification_tier({"action": "apply", "state": state.state}), message=f"Applied {', '.join(target_ids)}")
        deliver_notification(event, resolve_target(canonical_target_path(manifests[0].kind, manifests[0].target_id, _repo())).tenant)
        _write_log(run_id, "apply", [f"- Targets: {', '.join(target_ids)}", f"- Summary: `{summary_path}`"])
        print(f"[scaffold apply] run-id: {run_id}")
        return 0
    except Exception as exc:
        state.state = "rollback_pending"
        rollback_path = run_dir / "rollback.json"
        if not rollback_path.exists():
            write_json(rollback_path, {"run_id": run_id, "files": [], "config_ops": []})
        try:
            rollback_run(run_id, _repo())
            print(f"[scaffold apply] rollback completed for {run_id}", file=sys.stderr)
        except Exception as rollback_exc:  # pragma: no cover - exercised via integration tests
            print(f"[scaffold apply] rollback failed: {rollback_exc}", file=sys.stderr)
            return 3
        print(f"[scaffold apply] failed: {exc}", file=sys.stderr)
        return 2
    finally:
        state.release_lock()


def handle_rollback(args: Namespace) -> int:
    # Try proposal-level rollback first
    try:
        rollback_run(args.run_id, _repo())
        print(f"[scaffold rollback] run-id: {args.run_id}")
        return 0
    except Exception:
        pass

    # Fallback: try backup-based rollback (from adopt workflow)
    try:
        from clawscaffold.backup import restore_backup as _restore_backup
        manifest = _restore_backup(args.run_id, _repo())
        restored_files = manifest.get("files", [])
        print(f"[scaffold rollback] restored {len(restored_files)} files from backup for run-id: {args.run_id}")
        return 0
    except FileNotFoundError:
        print(f"[scaffold rollback] no rollback data found for run-id: {args.run_id}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"[scaffold rollback] failed: {exc}", file=sys.stderr)
        return 3


def _handle_org_chart_adopt(args: Namespace) -> int:
    """Handle ``scaffold adopt --org-chart``.

    Builds an org-chart interview (one question per agent), prints the
    questions as JSON, reads answers from stdin, applies them, and
    reports the result.
    """
    run_id, run_dir = _run_dir("org-chart")
    questions = build_org_chart_interview(_repo())
    if not questions:
        print("[scaffold adopt --org-chart] no agents found in catalog", file=sys.stderr)
        return 1

    # Emit questions
    questions_path = run_dir / "org-chart-questions.json"
    write_json(questions_path, questions)
    print(json.dumps(questions, indent=2))

    # Read answers from stdin (JSON object: {agent_id: reports_to_value})
    try:
        raw = sys.stdin.read()
        raw_answers: dict[str, str] = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[scaffold adopt --org-chart] invalid JSON input: {exc}", file=sys.stderr)
        return 1

    result = apply_org_chart_answers(raw_answers, _repo())
    result_path = run_dir / "org-chart-result.json"
    write_json(result_path, result)

    _write_summary(
        run_id,
        "org-chart",
        "applied" if not result["errors"] else "applied_with_errors",
        list(raw_answers.keys()),
        {"questions": str(questions_path), "result": str(result_path)},
    )

    print(f"[scaffold adopt --org-chart] run-id: {run_id}")
    print(f"[scaffold adopt --org-chart] updated: {result['updated']} agents")
    if result["errors"]:
        for err in result["errors"]:
            print(f"  ERROR: {err}", file=sys.stderr)
    if result["warnings"]:
        for warn in result["warnings"]:
            print(f"  WARNING: {warn}", file=sys.stderr)

    return 1 if result["errors"] else 0


def handle_adopt(args: Namespace) -> int:
    if getattr(args, "org_chart", False):
        return _handle_org_chart_adopt(args)

    if args.promote:
        promote_to_managed(args.promote, _repo(), args.run_id)
        print(f"[scaffold adopt] promoted: {args.promote}")
        return 0

    sync_adoption_inventory(_repo())
    kind, target_id = infer_target_from_runtime_path(args.path, _repo())
    target_path = canonical_target_path(kind, target_id, _repo())
    existing_entry = find_adoption_entry(kind, target_id, _repo())
    run_id, run_dir = _run_dir("adopt")
    if not args.force and existing_entry and existing_entry.get("status") != "untracked":
        registry_path = adoption_registry_path(_repo())
        _write_summary(
            run_id,
            "adopt",
            "blocked",
            [target_id],
            {"registry": str(registry_path), "canonical_spec": str(target_path)},
        )
        _write_log(
            run_id,
            "adopt",
            [
                f"- Blocked duplicate adoption for `{target_id}`",
                f"- Status: `{existing_entry.get('status', 'unknown')}`",
                f"- Registry: `{registry_path}`",
                "- Re-run with `--force` to overwrite the canonical draft intentionally.",
            ],
        )
        print(
            f"[scaffold adopt] blocked: {target_id} is already {existing_entry.get('status')} in {adoption_registry_path(_repo())}. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1
    if not args.force and target_path.exists():
        print(f"[scaffold adopt] blocked: canonical spec already exists at {target_path}. Use --force to overwrite.", file=sys.stderr)
        return 1

    draft = generate_draft_spec(args.path, _repo())
    report = generate_migration_report(draft, args.path)
    draft["provenance"]["created_by_run"] = run_id
    write_yaml(target_path, draft)
    registry_path = record_adoption_event(draft["kind"], draft["id"], args.path, action="adopt", root=_repo(), run_id=run_id)
    report_path = run_dir / "migration-report.json"
    write_json(report_path, report.__dict__)
    proposal = create_proposal(
        action="adopt",
        target_id=draft["id"],
        proposer="human:scaffold-cli",
        tenant=draft.get("tenant", default_tenant_name(_repo())),
        payload={"runtime_path": args.path, "stage": 1, "inferred_id": draft["id"], "inferred_kind": draft["kind"]},
    )
    proposal = proposal.__class__(**{**proposal.to_dict(), "run_id": run_id})
    write_proposal(proposal, run_dir)
    _write_summary(
        run_id,
        "adopt",
        "proposed",
        [draft["id"]],
        {"draft_spec": str(target_path), "migration_report": str(report_path), "registry": str(registry_path)},
    )
    print(f"[scaffold adopt] run-id: {run_id}")
    print(f"[scaffold adopt] draft spec: {target_path}")
    return 0


def handle_qa(args: Namespace) -> int:
    run_id, _run_dir_unused = _run_dir("qa")
    artifacts = {}
    for target_id in _selected_targets(args):
        kind, _ = _load_target_path(target_id)
        resolved = resolve_target(canonical_target_path(kind, target_id, _repo()))
        path = render_qa_outputs(resolved, _repo())
        artifacts[target_id] = {"scenarios": str(path), "runner_configured": check_runner_configured(resolved.tenant)}
        event = NotificationEvent(run_id=run_id, tier=classify_notification_tier({"action": "qa", "state": "completed"}), message=f"QA artifacts generated for {target_id}")
        deliver_notification(event, resolved.tenant)
    _write_summary(run_id, "qa", "completed", list(artifacts.keys()), artifacts)
    print(f"[scaffold qa] run-id: {run_id}")
    return 0


def handle_audit(args: Namespace) -> int:
    # Handle --graph and --channels audit modes
    if getattr(args, "graph", False):
        from clawscaffold.graph_validator import audit_graph as _audit_graph
        result = _audit_graph(canonical_target_path("agent", "", _repo()).parent.parent)
        print(f"Graph audit: {result.agent_count} agents, {result.edge_count} edges")
        for err in result.errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        for warn in result.warnings:
            print(f"  WARNING: {warn}")
        print(f"  Manages derivation: {len(result.derived_manages)} agents")
        print(f"  Result: {'PASS' if result.valid else 'FAIL'}")
        return 0 if result.valid else 1

    if getattr(args, "channels", False):
        from clawscaffold.audit import audit_channels as _audit_channels
        findings = _audit_channels(canonical_target_path("agent", "", _repo()).parent.parent)
        if not findings:
            print("Channel audit: no duplicate bindings found")
            return 0
        for finding in findings:
            print(f"  {finding['severity'].upper()}: {finding['binding_key']} claimed by {finding['claimed_by']}")
            print(f"    {finding['recommendation']}")
        return 1 if any(f["severity"] == "error" for f in findings) else 0

    target_ids = _selected_targets(args)
    run_id, run_dir = _run_dir("audit")
    reports: list[dict[str, Any]] = []
    decisions_path: Path | None = None
    for target_id in target_ids:
        kind = _load_target_path(target_id)[0] if args.all else _infer_kind(target_id, args.kind)
        if not kind:
            print(f"[scaffold audit] could not infer target kind for {target_id}", file=sys.stderr)
            return 1
        if args.kind and kind != args.kind:
            continue
        sections = _load_runtime_sections(kind, target_id)
        spec_path = canonical_target_path(kind, target_id, _repo())
        spec = read_yaml(spec_path) if spec_path.exists() else (
            build_default_agent_spec(target_id, default_tenant_name(_repo()))
            if kind == "agent"
            else build_default_skill_spec(target_id, default_tenant_name(_repo()))
        )
        audit = build_audit_report(target_id, kind, "extend", sections, spec, _repo(), behavioral=args.behavioral, run_id=run_id)
        readiness = assess_migration_readiness(target_id, kind, spec, _repo())
        reports.append({"target_id": target_id, "kind": kind, "audit": audit.to_dict(), "migration_readiness": readiness})

        if args.all:
            continue

        state = InterviewState(
            run_id=run_id,
            mode="extend",
            target_kind=kind,
            target_id=target_id,
            builder_identity="human:scaffold-cli",
            sections={section.id: section for section in sections},
            policy_hints=infer_policy_hints(sections),
            questions=[],
            current_question_index=-1,
            answers={},
            pass_number=2,
            content_hash=sha256_prefix(runtime_file_for_target(kind, target_id, _repo()).read_text(encoding="utf-8"))
            if runtime_file_for_target(kind, target_id, _repo()).exists()
            else None,
            status="assembled",
            created_at=now_iso(),
            updated_at=now_iso(),
            execution_env="cli",
        )
        brief = generate_review_brief(state, audit, _repo())
        brief_path = _repo() / "catalog" / f"{kind}s" / f"{target_id}.review.md"
        entry = ReviewQueueEntry(
            target_key=f"{kind}:{target_id}",
            target_kind=kind,
            target_id=target_id,
            mode="extend",
            builder_identity="human:scaffold-cli",
            run_id=run_id,
            confidence_score=audit.confidence_score,
            review_priority=audit.review_priority,
            status="pending",
            review_brief_path=str(brief_path.relative_to(_repo())),
            transcript_path=brief.transcript_path,
            created_at=now_iso(),
        )
        add_review_queue_entry(entry, _repo())
        decisions_path = _apply_clawspec_artifacts(audit, run_id, kind=kind, target_id=target_id)

    report_path = run_dir / "audit-report.json"
    write_json(report_path, {"run_id": run_id, "reports": reports})
    print(f"[scaffold audit] run-id: {run_id}")
    if not args.all and decisions_path:
        print(f"[scaffold audit] clawspec decisions: {decisions_path}")
    if args.all:
        unsafe = 0
        for item in reports:
            readiness = item["migration_readiness"]
            audit = item["audit"]
            preservation = readiness.get("preservation_report", {})
            pct = preservation.get("preservation_pct", "n/a") if preservation else "n/a"
            status = "safe" if readiness["safe_for_apply"] else "unsafe"
            if status == "unsafe":
                unsafe += 1
            print(
                f"{item['kind']}:{item['target_id']}\t{status}\tshallow={readiness['shallow_spec']}\t"
                f"preservation={pct}\tconfidence={audit['confidence_score']}"
            )
        print(f"[scaffold audit] unsafe targets: {unsafe}/{len(reports)}")
    else:
        readiness = reports[0]["migration_readiness"]
        audit = reports[0]["audit"]
        preservation = readiness.get("preservation_report", {})
        pct = preservation.get("preservation_pct", "n/a") if preservation else "n/a"
        print(f"[scaffold audit] confidence: {audit['confidence_score']} ({audit['review_priority']})")
        print(f"[scaffold audit] safe_for_apply: {readiness['safe_for_apply']}")
        print(f"[scaffold audit] shallow_spec: {readiness['shallow_spec']}")
        print(f"[scaffold audit] preservation: {pct}")
    print(f"[scaffold audit] report: {report_path}")
    return 0


def handle_backfill(args: Namespace) -> int:
    run_id, run_dir = _run_dir("backfill")
    results: list[dict[str, Any]] = []
    for target_id in _selected_targets(args):
        kind = _load_target_path(target_id)[0] if args.all else _infer_kind(target_id, args.kind)
        if not kind:
            print(f"[scaffold backfill] could not infer target kind for {target_id}", file=sys.stderr)
            return 1
        if args.kind and kind != args.kind:
            continue

        spec_path = canonical_target_path(kind, target_id, _repo())
        runtime_path = runtime_file_for_target(kind, target_id, _repo())
        if not spec_path.exists():
            results.append({"target_id": target_id, "kind": kind, "status": "blocked", "reason": "canonical spec missing"})
            continue
        if not runtime_path.exists():
            results.append({"target_id": target_id, "kind": kind, "status": "blocked", "reason": "runtime file missing"})
            continue

        existing = read_yaml(spec_path)
        before = assess_migration_readiness(target_id, kind, existing, _repo())
        if not before["shallow_spec"] and not args.force:
            results.append({"target_id": target_id, "kind": kind, "status": "skipped", "before": before, "after": before})
            continue

        original_text = spec_path.read_text(encoding="utf-8")
        candidate = build_backfilled_spec(target_id, kind, root=_repo(), existing_spec=existing)
        validate_dict(candidate, "target.schema.json", _repo())
        try:
            write_yaml(spec_path, candidate)
            _render_one(target_id, run_dir)
            validation = _validate_rendered(target_id)
            if validation["errors"]:
                raise ValueError(f"rendered validation failed: {validation['errors']}")
            after = assess_migration_readiness(target_id, kind, candidate, _repo())
        except Exception as exc:
            write_text(spec_path, original_text)
            results.append(
                {
                    "target_id": target_id,
                    "kind": kind,
                    "status": "failed",
                    "before": before,
                    "error": str(exc),
                }
            )
            continue

        results.append({"target_id": target_id, "kind": kind, "status": "backfilled", "before": before, "after": after})

    report_path = run_dir / "backfill-report.json"
    write_json(report_path, {"run_id": run_id, "results": results})
    print(f"[scaffold backfill] run-id: {run_id}")
    for item in results:
        after = item.get("after", {})
        preservation = after.get("preservation_report", {}) if after else {}
        pct = preservation.get("preservation_pct", "n/a") if preservation else "n/a"
        print(f"{item['kind']}:{item['target_id']}\t{item['status']}\tpreservation={pct}")
    print(f"[scaffold backfill] report: {report_path}")
    return 0


def handle_review(args: Namespace) -> int:
    if args.show:
        target_key = args.show
        entries = {entry.target_key: entry for entry in list_review_entries(_repo())}
        entry = entries.get(target_key)
        if entry is None:
            print(f"[scaffold review] entry not found: {target_key}", file=sys.stderr)
            return 1
        print((_repo() / entry.review_brief_path).read_text(encoding="utf-8"))
        return 0
    if args.mark_reviewed:
        update_review_entry(args.mark_reviewed, "reviewed", args.reviewer or "human:scaffold-cli", _repo())
        print(f"[scaffold review] marked reviewed: {args.mark_reviewed}")
        return 0
    if args.dismiss:
        update_review_entry(args.dismiss, "dismissed", args.reviewer or "human:scaffold-cli", _repo())
        print(f"[scaffold review] dismissed: {args.dismiss}")
        return 0

    entries = list_review_entries(_repo())
    if not entries:
        print("[scaffold review] queue empty")
        return 0
    for entry in entries:
        print(
            f"{entry.target_key}\t{entry.review_priority}\t{entry.confidence_score}\t{entry.status}\t{entry.review_brief_path}"
        )
    return 0


def handle_interview(args: Namespace) -> int:
    run_id, run_dir = _run_dir("interview")
    if args.resume:
        state = load_state_for_resume(args.resume, _repo())
        if state.mode == "adopt":
            resumed_state, payload = analyze_run(
                mode=state.mode,
                kind=state.target_kind,
                target_id=state.target_id,
                execution_style="interactive",
                root=_repo(),
                resume_run_id=args.resume,
                builder_identity=state.builder_identity,
                execution_env=state.execution_env or "cli",
            )
            return _run_adopt_planner_shell(resumed_state, payload)
        current_hash = runtime_hash_for_state(state, _repo())
        if current_hash and state.content_hash and current_hash != state.content_hash:
            print("[scaffold interview] warning: runtime file changed since this run started", file=sys.stderr)
    else:
        inferred = _infer_context_target()
        target_id = args.id
        kind = _infer_kind(args.id, args.kind)
        mode = args.mode

        if not target_id and inferred:
            inferred_kind, inferred_id = inferred
            answer = (_prompt(f"Use inferred target {inferred_kind}:{inferred_id}? [Y/n]") or "y").lower()
            if answer not in {"n", "no"}:
                kind, target_id = inferred_kind, inferred_id
                mode = mode or "extend"

        if not mode:
            mode = _prompt("Mode [create/adopt/extend]:") or "create" if not target_id else mode
        if not kind:
            kind = _prompt("Kind [agent/skill/tenant/brand/site]:") or "agent"
        if not target_id:
            target_id = _prompt("Target id:")
        if not mode:
            runtime_exists = runtime_file_for_target(kind, target_id, _repo()).exists()
            spec_exists = canonical_target_path(kind, target_id, _repo()).exists()
            if spec_exists and runtime_exists:
                mode = "extend"
            elif runtime_exists:
                mode = "adopt"
            else:
                mode = "create"

        if args.pass_name == "policy":
            if not canonical_target_path(kind, target_id, _repo()).exists():
                print("[scaffold interview] --pass policy requires an existing canonical spec", file=sys.stderr)
                return 1
            state = create_interview_state(mode, kind, target_id, "human:scaffold-cli", root=_repo(), execution_env="cli")
            state.questions = []
            state.current_question_index = -1
            state = append_policy_pass(state, root=_repo())
        elif mode == "extend":
            sections = _load_runtime_sections(kind, target_id)
            section_map = {section.id: section for section in sections}
            spec_path = canonical_target_path(kind, target_id, _repo())
            spec = read_yaml(spec_path) if spec_path.exists() else (
                build_default_agent_spec(target_id, default_tenant_name(_repo()))
                if kind == "agent"
                else build_default_skill_spec(target_id, default_tenant_name(_repo()))
            )
            audit = build_audit_report(target_id, kind, "extend", sections, spec, _repo(), behavioral=False, run_id=run_id)
            missing = [item["rule_id"].replace("required_", "") for item in audit.structural_checks if not item.get("passed")]
            needs_attention = sorted({item.get("section_id") for item in audit.heuristic_findings if item.get("section_id")})
            strong = [section.id for section in sections if section.id not in set(missing) | set(needs_attention)]
            if strong:
                print(f"[scaffold interview] strong: {', '.join(strong)}")
            if needs_attention:
                print(f"[scaffold interview] needs attention: {', '.join(needs_attention)}")
            if missing:
                print(f"[scaffold interview] missing: {', '.join(missing)}")
            selected = _prompt("Sections to improve (comma separated, blank = flagged sections):")
            if selected:
                selected_sections = [item.strip() for item in selected.split(",") if item.strip()]
            else:
                selected_sections = needs_attention or missing or list(section_map.keys())[:1]
            state = create_interview_state(
                mode,
                kind,
                target_id,
                "human:scaffold-cli",
                root=_repo(),
                execution_env="cli",
                selected_sections=selected_sections,
            )
        elif mode == "adopt":
            planner_state, payload = analyze_run(
                mode="adopt",
                kind=kind,
                target_id=target_id,
                execution_style="interactive",
                root=_repo(),
                builder_identity="human:scaffold-cli",
                execution_env="cli",
            )
            return _run_adopt_planner_shell(planner_state, payload)
        else:
            state = create_interview_state(mode, kind, target_id, "human:scaffold-cli", root=_repo(), execution_env="cli")

    while True:
        while state.current_question_index >= 0:
            question = state.questions[state.current_question_index]
            print(f"[scaffold interview] {question.prompt_text}")
            if question.question_type == "multiple_choice":
                for choice in question.choices:
                    marker = " (recommended)" if choice["value"] == question.recommended_choice else ""
                    print(f"  - {choice['value']}: {choice['description']}{marker}")
                answer = _prompt(">") or question.recommended_choice or ""
                state = process_answer(state, answer, root=_repo())
            elif question.question_type == "gap_fill":
                if question.extracted_value:
                    print(question.extracted_value)
                answer = _prompt(">") or str(question.extracted_value or "")
                state = process_answer(state, answer, root=_repo())
            elif question.question_type == "confirmation":
                if question.extracted_value:
                    print(question.extracted_value)
                choice = (_prompt("[K]eep / [e]dit / [r]egenerate?") or "k").lower()
                if choice.startswith("e"):
                    edited = _prompt("Edited content:")
                    answer = {"action": "edit", "content": edited or str(question.extracted_value or "")}
                elif choice.startswith("r"):
                    answer = _prompt_draft_acceptance(question, state)
                else:
                    answer = {"action": "keep", "content": str(question.extracted_value or "")}
                state = process_answer(state, answer, root=_repo())
            else:
                if question.extracted_value:
                    print(question.extracted_value)
                answer = _prompt_draft_acceptance(question, state)
                state = process_answer(state, answer, root=_repo())

        if args.pass_name == "policy":
            break
        if state.pass_number == 1 and not any(question.id.startswith("policy.") for question in state.questions):
            tune = (_prompt("Want to tune policy settings? [y/N]") or "n").lower()
            if tune in {"y", "yes"}:
                state = append_policy_pass(state, root=_repo())
                continue
        break

    state.run_id = run_id
    state.save(_repo() / "compiler" / "runs" / run_id / "interview.json")
    if args.auto_apply:
        result = auto_apply_pipeline(state, _repo())
        audit_payload = read_json(Path(result["audit_report"]))
        decisions_path = _apply_clawspec_artifacts(
            audit_payload,
            run_id,
            kind=state.target_kind,
            target_id=state.target_id,
        )
        print(f"[scaffold interview] run-id: {run_id}")
        print(f"[scaffold interview] spec: {result['spec_path']}")
        print(f"[scaffold interview] review: {result['review_brief']}")
        if decisions_path:
            print(f"[scaffold interview] clawspec decisions: {decisions_path}")
        return 0

    target_path = _persist_interview_spec(state, run_dir)
    audit = build_audit_report(
        state.target_id,
        state.target_kind,
        mode,
        list(state.sections.values()),
        read_yaml(target_path),
        _repo(),
        behavioral=True,
        run_id=run_id,
    )
    audit_path = _repo() / "compiler" / "runs" / run_id / "audit-report.json"
    write_json(audit_path, audit.to_dict())
    brief = generate_review_brief(state, audit, _repo())
    brief_path = _repo() / "catalog" / f"{state.target_kind}s" / f"{state.target_id}.review.md"
    add_review_queue_entry(
        ReviewQueueEntry(
            target_key=f"{state.target_kind}:{state.target_id}",
            target_kind=state.target_kind,
            target_id=state.target_id,
            mode=mode,
            builder_identity=state.builder_identity,
            run_id=run_id,
            confidence_score=audit.confidence_score,
            review_priority=audit.review_priority,
            status="pending",
            review_brief_path=str(brief_path.relative_to(_repo())),
            transcript_path=brief.transcript_path,
            created_at=now_iso(),
        ),
        _repo(),
    )
    decisions_path = _apply_clawspec_artifacts(audit, run_id, kind=state.target_kind, target_id=state.target_id)
    print(f"[scaffold interview] run-id: {run_id}")
    print(f"[scaffold interview] spec: {target_path}")
    print(f"[scaffold interview] rendered: {generated_target_dir(state.target_kind, state.target_id, _repo())}")
    print(f"[scaffold interview] review: {brief_path}")
    if decisions_path:
        print(f"[scaffold interview] clawspec decisions: {decisions_path}")
    return 0


def handle_upgrade(args: Namespace) -> int:
    """Patch existing 0.1.0 specs with 0.2.0 defaults."""
    target_ids = _selected_targets(args)
    upgraded = 0
    for target_id in target_ids:
        kind, _ = _load_target_path(target_id) if args.all else (_infer_kind(target_id, None), None)
        if not kind:
            continue
        spec_path = canonical_target_path(kind, target_id, _repo())
        if not spec_path.exists():
            continue
        spec = read_yaml(spec_path)
        version = spec.get("schema_version", "0.1.0")
        if version >= "0.2.0":
            continue

        # Patch defaults for new fields
        spec.setdefault("org", {}).setdefault("reports_to", None)
        spec["org"].setdefault("org_level", "ic")
        spec["org"].setdefault("manages", [])
        spec.setdefault("operation", {}).setdefault("coordination", {"pattern": "standalone", "can_spawn": False, "max_spawn_depth": 0})
        spec["operation"].setdefault("escalation", {"chain": ["operator"], "timeout_seconds": 300, "fallback_behavior": "escalate"})
        spec["operation"].setdefault("scheduling", {"quiet_hours": None, "max_concurrent": 1, "sla_response_seconds": 3600})
        spec["operation"].setdefault("resilience", {"fallback_agent": None, "degraded_mode": None, "circuit_breaker_threshold": 3})
        spec.setdefault("policy", {}).setdefault("resource_limits", {"max_tokens_per_session": 50000, "max_sessions_per_day": 100, "max_outbound_per_day": 50, "rate_limits": {}})
        spec["policy"].setdefault("compliance", {"data_classification": "internal", "handles_pii": False, "handles_phi": False, "retention_days": 90})
        spec["policy"].setdefault("observability", {"log_level": "standard", "cost_tracking": True, "alert_on_failure": False, "paperclip_sync": True})
        spec.setdefault("governance", {"visibility": "internal", "approval_tier": "medium", "risk_tier": "low", "budget_tier": "standard", "monthly_usd_cap": 50, "paperclip": {"export": kind == "agent"}})
        if kind == "skill":
            spec.setdefault("skill", {}).setdefault("owned_by_agents", [])
            spec["skill"].setdefault("scope", "workspace")
        spec["schema_version"] = "0.2.0"

        if args.dry_run:
            print(f"[scaffold upgrade] would upgrade {target_id} from {version} to 0.2.0")
        else:
            write_yaml(spec_path, spec)
            print(f"[scaffold upgrade] upgraded {target_id} from {version} to 0.2.0")
        upgraded += 1

    print(f"[scaffold upgrade] {'would upgrade' if args.dry_run else 'upgraded'} {upgraded} specs")
    return 0


def handle_governance_audit(args: Namespace) -> int:
    from clawscaffold.organization_audit import run_organization_audit

    result = run_organization_audit(_repo())
    if result["errors"]:
        print("ERRORS:")
        for error in result["errors"]:
            print(f"  - {error}")
    if result["warnings"]:
        print("WARNINGS:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    if result["passed"]:
        print("governance-audit: PASSED")
        return 0
    print(f"governance-audit: FAILED ({len(result['errors'])} errors)")
    return 1


def handle_export_paperclip(args: Namespace) -> int:
    from clawscaffold.paperclip_export import export_all

    try:
        result = export_all(_repo())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"export-paperclip: wrote {result['agents_exported']} agents, {result['teams']} teams to {result['export_dir']}")
    return 0


def handle_skill(args: Namespace) -> int:
    """
    Dispatcher for `openclaw skill` subcommands.

    Subcommands:
      find <query>      Search installed skills for a query string
      recommend <query> Like find, but returns top 5 and suggests catalog alternatives
      scan <path>       Run a static security scan on a SKILL.md file
      add <source:name> Install a skill source via SkillKit (install succeeds or fails)
    """
    from clawscaffold.skill_catalog import build_catalog, format_skill_result, scan_skill_md, search_catalog
    from clawscaffold.skill_tree import build_capability_tree

    skill_cmd = getattr(args, "skill_command", None)

    if skill_cmd == "find":
        query = args.query
        catalog = build_catalog()
        results = search_catalog(query, catalog=catalog, min_trust_score=0.0, max_results=10)
        if not results:
            print(f"skill find: no results for '{query}'")
            return 0
        print(f"skill find: {len(results)} result(s) for '{query}'\n")
        for skill in results:
            print(format_skill_result(skill))
            print()
        return 0

    if skill_cmd == "recommend":
        query = args.query
        catalog = build_catalog()
        results = search_catalog(query, catalog=catalog, min_trust_score=0.5, max_results=5)
        if not results:
            print(f"skill recommend: no local matches for '{query}'")
            print("  Suggestion: run `openclaw skill add skillkit:<skill-name>` to install from catalog.")
            return 0
        print(f"skill recommend: top {len(results)} match(es) for '{query}'\n")
        for skill in results:
            print(format_skill_result(skill))
            print()
        return 0

    if skill_cmd == "scan":
        path = Path(args.path)
        if not path.exists():
            print(f"skill scan: file not found: {path}", file=sys.stderr)
            return 1
        status = scan_skill_md(path)
        if status == "blocked":
            print(f"skill scan: BLOCKED — toxic patterns detected in {path}")
            print("  The skill is NOT activated. Fix the flagged patterns before proceeding.")
            return 2
        if status == "warnings":
            print(f"skill scan: WARNINGS — elevated-permission patterns detected in {path}")
            print("  Review carefully before activating. Run with operator confirmation.")
            return 0
        print(f"skill scan: CLEAN — no suspicious patterns found in {path}")
        return 0

    if skill_cmd == "add":
        source_name = getattr(args, "source_name", "")
        if not source_name:
            print("skill add: usage: openclaw skill add <source>:<skill-name>", file=sys.stderr)
            return 1
        if ":" not in source_name:
            print(f"skill add: expected format <source>:<name>, got '{source_name}'", file=sys.stderr)
            return 1
        import shutil
        if shutil.which("skillkit") is None:
            print(
                "skill add: BLOCKED — 'skillkit' is not installed.\n"
                "  Install with: npm install -g skillkit\n"
                "  Skill installation is blocked without skillkit scan.",
                file=sys.stderr,
            )
            return 1
        import subprocess
        print(f"skill add: installing {source_name} via skillkit (scan enforced)...")
        result = subprocess.run(
            ["skillkit", "install", source_name, "--yes", "--scan"],
            capture_output=True,
            text=True,
            cwd=str(_repo()),
        )
        if result.returncode != 0:
            print(f"skill add: install FAILED for {source_name}", file=sys.stderr)
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
            print("  Skill NOT installed. Fix scan/install errors and try again.", file=sys.stderr)
            return 1
        print(f"skill add: install PASSED for {source_name}")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        print("  Review the installed skill before first use.")
        return 0

    # Fallback: print help
    print("Usage: openclaw skill <find|recommend|scan|add> [args]")
    return 0


def cmd_init(args: Namespace) -> int:
    """Initialize a clawscaffold project by creating a .clawscaffold marker file."""
    marker = Path.cwd() / ".clawscaffold"
    if marker.exists() and not getattr(args, "force", False):
        print(f"Project already initialized: {marker}")
        return 0
    marker.write_text(
        f"# ClawScaffold project marker\n# Created: {datetime.now().isoformat()}\n"
    )
    print(f"Initialized clawscaffold project at {Path.cwd()}")
    return 0


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init: initialize a clawscaffold project
    init_parser = subparsers.add_parser("init", help="Initialize a clawscaffold project")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing marker")
    init_parser.set_defaults(func=cmd_init)

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--non-interactive", action="store_true")
    create_parser.add_argument("--kind", choices=["agent", "skill", "tenant", "brand", "site"], required=True)
    create_parser.add_argument("--id", required=True)
    create_parser.add_argument("--tenant")
    create_parser.set_defaults(func=handle_create)

    interview_parser = subparsers.add_parser("interview")
    interview_parser.add_argument("--mode", choices=["create", "adopt", "extend"])
    interview_parser.add_argument("--kind", choices=["agent", "skill", "tenant", "brand", "site"])
    interview_parser.add_argument("--id")
    interview_parser.add_argument("--auto-apply", action="store_true")
    interview_parser.add_argument("--resume")
    interview_parser.add_argument("--pass", dest="pass_name", choices=["policy"])
    interview_parser.set_defaults(func=handle_interview)

    interview_agent_parser = subparsers.add_parser("interview-agent")
    interview_agent_subparsers = interview_agent_parser.add_subparsers(dest="interview_agent_command", required=True)

    interview_agent_analyze = interview_agent_subparsers.add_parser("analyze")
    interview_agent_analyze.add_argument("--mode", choices=["create", "adopt", "extend"])
    interview_agent_analyze.add_argument("--kind", choices=["agent", "skill", "tenant", "brand", "site"])
    interview_agent_analyze.add_argument("--id")
    interview_agent_analyze.add_argument("--execution-style", choices=["interactive", "accept_recommendations"], default="interactive")
    interview_agent_analyze.add_argument("--resume")
    interview_agent_analyze.set_defaults(func=handle_interview_agent_analyze)

    interview_agent_next = interview_agent_subparsers.add_parser("next-question")
    interview_agent_next.add_argument("--run-id", required=True)
    interview_agent_next.set_defaults(func=handle_interview_agent_next_question)

    interview_agent_answer = interview_agent_subparsers.add_parser("answer")
    interview_agent_answer.add_argument("--run-id", required=True)
    interview_agent_answer.add_argument("--question-id", required=True)
    interview_agent_answer.add_argument("--choice")
    interview_agent_answer.add_argument("--content-file")
    interview_agent_answer.add_argument("--value-json")
    interview_agent_answer.set_defaults(func=handle_interview_agent_answer)

    interview_agent_finalize = interview_agent_subparsers.add_parser("finalize")
    interview_agent_finalize.add_argument("--run-id", required=True)
    interview_agent_finalize.add_argument("--accept-recommendations", action="store_true")
    interview_agent_finalize.set_defaults(func=handle_interview_agent_finalize)

    render_parser = subparsers.add_parser("render")
    render_group = render_parser.add_mutually_exclusive_group(required=True)
    render_group.add_argument("--id")
    render_group.add_argument("--all", action="store_true")
    render_parser.set_defaults(func=handle_render)

    validate_parser = subparsers.add_parser("validate")
    validate_group = validate_parser.add_mutually_exclusive_group(required=True)
    validate_group.add_argument("--id")
    validate_group.add_argument("--all", action="store_true")
    validate_parser.set_defaults(func=handle_validate)

    apply_parser = subparsers.add_parser("apply")
    apply_group = apply_parser.add_mutually_exclusive_group(required=True)
    apply_group.add_argument("--id")
    apply_group.add_argument("--all", action="store_true")
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.add_argument("--force", action="store_true")
    apply_parser.set_defaults(func=handle_apply)

    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--run-id", required=True)
    rollback_parser.set_defaults(func=handle_rollback)

    adopt_parser = subparsers.add_parser("adopt")
    adopt_parser.add_argument("--path")
    adopt_parser.add_argument("--promote")
    adopt_parser.add_argument("--run-id")
    adopt_parser.add_argument("--force", action="store_true")
    adopt_parser.add_argument("--org-chart", action="store_true", help="Run org-chart hierarchy wiring interview")
    adopt_parser.set_defaults(func=handle_adopt)

    qa_parser = subparsers.add_parser("qa")
    qa_group = qa_parser.add_mutually_exclusive_group(required=True)
    qa_group.add_argument("--id")
    qa_group.add_argument("--all", action="store_true")
    qa_parser.set_defaults(func=handle_qa)

    audit_parser = subparsers.add_parser("audit")
    audit_group = audit_parser.add_mutually_exclusive_group(required=True)
    audit_group.add_argument("--id")
    audit_group.add_argument("--all", action="store_true")
    audit_group.add_argument("--graph", action="store_true", help="Run org chart graph audit")
    audit_group.add_argument("--channels", action="store_true", help="Run channel binding audit")
    audit_parser.add_argument("--kind", choices=["agent", "skill", "tenant", "brand", "site"])
    audit_parser.add_argument("--behavioral", action="store_true")
    audit_parser.set_defaults(func=handle_audit)

    backfill_parser = subparsers.add_parser("backfill")
    backfill_group = backfill_parser.add_mutually_exclusive_group(required=True)
    backfill_group.add_argument("--id")
    backfill_group.add_argument("--all", action="store_true")
    backfill_parser.add_argument("--kind", choices=["agent", "skill", "tenant", "brand", "site"])
    backfill_parser.add_argument("--force", action="store_true")
    backfill_parser.set_defaults(func=handle_backfill)

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("--list", action="store_true")
    review_parser.add_argument("--show")
    review_parser.add_argument("--mark-reviewed")
    review_parser.add_argument("--dismiss")
    review_parser.add_argument("--reviewer")
    review_parser.set_defaults(func=handle_review)

    upgrade_parser = subparsers.add_parser("upgrade")
    upgrade_group = upgrade_parser.add_mutually_exclusive_group(required=True)
    upgrade_group.add_argument("--id")
    upgrade_group.add_argument("--all", action="store_true")
    upgrade_parser.add_argument("--dry-run", action="store_true")
    upgrade_parser.set_defaults(func=handle_upgrade)

    gov_audit_parser = subparsers.add_parser("governance-audit")
    gov_audit_parser.set_defaults(func=handle_governance_audit)

    export_parser = subparsers.add_parser("export-paperclip")
    export_parser.set_defaults(func=handle_export_paperclip)

    # --- Skill discovery subparser ---
    skill_parser = subparsers.add_parser(
        "skill",
        help="Discover, scan, and install skills from the workspace and external catalogs",
    )
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command", required=True)
    skill_parser.set_defaults(func=handle_skill)

    # find: search installed skills
    skill_find_parser = skill_subparsers.add_parser("find", help="Search installed skills for a query")
    skill_find_parser.add_argument("query", help="Natural language search query (e.g. 'send email via resend')")
    skill_find_parser.set_defaults(func=handle_skill)

    # recommend: find + catalog suggestion
    skill_recommend_parser = skill_subparsers.add_parser("recommend", help="Find top matches and suggest catalog alternatives")
    skill_recommend_parser.add_argument("query", help="Natural language search query")
    skill_recommend_parser.set_defaults(func=handle_skill)

    # scan: static security scan on a SKILL.md file
    skill_scan_parser = skill_subparsers.add_parser("scan", help="Run security scan on a SKILL.md file")
    skill_scan_parser.add_argument("path", help="Path to the SKILL.md file to scan")
    skill_scan_parser.set_defaults(func=handle_skill)

    # add: install a skill from a catalog (requires skillkit scan)
    skill_add_parser = skill_subparsers.add_parser("add", help="Install a skill from a catalog source (requires skillkit scan)")
    skill_add_parser.add_argument("source_name", help="Source and skill name in <source>:<skill-name> format")
    skill_add_parser.set_defaults(func=handle_skill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SchemaValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
