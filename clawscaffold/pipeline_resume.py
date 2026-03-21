"""Pipeline resume logic for multi-agent orchestration.

Scans memory/pipelines/*/state.yaml for an in-progress pipeline matching
the requested type or ID, then determines the next action the caller should
take: resume, complete, restart, or escalate.
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from clawscaffold.pipeline_state import (
    append_audit,
    check_pipeline_terminal,
    is_legacy,
    mark_stage_running,
    mark_stage_stalled,
    read_state,
    reset_guards,
    write_state,
)

logger = logging.getLogger(__name__)

_ACTOR = "pipeline-resume"

try:
    from clawscaffold.contract_assertions import run_assertions as _run_assertions  # type: ignore[attr-defined]
    _ASSERTIONS_AVAILABLE = True
except ImportError:
    _ASSERTIONS_AVAILABLE = False
    warnings.warn("contract_assertions not available; skipping artifact re-validation", stacklevel=1)


@dataclass
class ResumeResponse:
    """Return value from resume_pipeline describing the next action."""

    action: str  # "resume" | "complete" | "restart" | "escalate"
    stage: str | None = None
    agent: str | None = None
    contract: str | None = None
    prior_work: dict[str, str] = field(default_factory=dict)
    reason: str | None = None


def resume_pipeline(
    pipeline_type: str | None = None,
    pipeline_id: str | None = None,
    *,
    repo_root: Path | None = None,
) -> ResumeResponse:
    """Scan for an in-progress pipeline and determine the next action.

    Args:
        pipeline_type: Filter to pipelines of this type (newsletter/campaign/website).
        pipeline_id: Select a specific pipeline by ID (takes precedence over type).
        repo_root: Repository root; defaults to three levels above this file.
    """
    if pipeline_type is None and pipeline_id is None:
        return ResumeResponse(action="restart", reason="pipeline_type or pipeline_id required")

    root = repo_root or Path(__file__).resolve().parents[2]
    state_path, state = _find_state(root / "memory" / "pipelines", pipeline_type, pipeline_id)
    if state_path is None or state is None:
        return ResumeResponse(action="restart", reason="no in-progress pipeline found")

    # Step 2: legacy schema guard.
    if is_legacy(state):
        return ResumeResponse(action="restart", reason="legacy state format")

    # Steps 3-4-7: revalidate artifacts, reset guards, mark stalls.
    _revalidate_completed(state, root)
    reset_guards(state)
    _mark_stalled_stages(state)

    # Steps 5-6-8-9: find next stage and decide.
    response = _decide_next(state)
    write_state(state_path, state)
    return response


def _find_state(
    pipelines_dir: Path,
    pipeline_type: str | None,
    pipeline_id: str | None,
) -> tuple[Path, dict[str, Any]] | tuple[None, None]:
    """Return (path, state) for the most recently updated in-progress pipeline."""
    if not pipelines_dir.exists():
        return None, None

    allowed_statuses = {"in_progress", "stalled"}
    if pipeline_id is not None:
        allowed_statuses.update({"completed", "failed"})

    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    for state_path in pipelines_dir.glob("*/state.yaml"):
        try:
            state = read_state(state_path)
        except (FileNotFoundError, ValueError):
            logger.warning("Skipping unreadable state file: %s", state_path)
            continue

        if state.get("status") not in allowed_statuses:
            continue
        if pipeline_id is not None and state.get("pipeline_id") != pipeline_id:
            continue
        if pipeline_id is None and pipeline_type is not None and state.get("pipeline_type") != pipeline_type:
            continue

        updated_raw = state.get("updated_at", "")
        try:
            updated = datetime.fromisoformat(updated_raw)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            updated = datetime.min.replace(tzinfo=UTC)

        candidates.append((updated, state_path, state))

    if not candidates:
        return None, None

    candidates.sort(key=lambda t: t[0], reverse=True)
    _, best_path, best_state = candidates[0]
    return best_path, best_state


def _revalidate_completed(state: dict[str, Any], repo_root: Path) -> None:
    """Mark completed stages failed when their artifacts no longer pass assertions."""
    if not _ASSERTIONS_AVAILABLE:
        return
    for stage in state.get("stages", []):
        if stage.get("status") != "completed" or not stage.get("contract"):
            continue

        roots = _candidate_workspace_roots(stage, repo_root)
        artifact = stage.get("artifact")
        if artifact and not any((root / artifact).exists() for root in roots):
            detail = f"artifact missing: {artifact}"
            stage.update({"status": "failed", "verification": "fail", "error_detail": detail})
            append_audit(state, "stage_failed", stage=stage["name"], actor=_ACTOR, detail=detail)
            continue

        detail = _revalidation_failure_detail(stage, roots)
        if detail is None:
            continue

        stage.update({"status": "failed", "verification": "fail", "error_detail": detail})
        append_audit(state, "stage_failed", stage=stage["name"], actor=_ACTOR, detail=detail)


def _candidate_workspace_roots(stage: dict[str, Any], repo_root: Path) -> list[Path]:
    """Return repo and agent workspace roots to consider during re-validation."""
    roots = [repo_root]
    agent_workspace = _resolve_agent_workspace(stage.get("agent"))
    if agent_workspace and agent_workspace not in roots:
        roots.append(agent_workspace)
    return roots


def _revalidation_failure_detail(stage: dict[str, Any], roots: list[Path]) -> str | None:
    """Return failure detail when no workspace validates the completed stage."""
    contract_rel = stage.get("contract")
    if not contract_rel:
        return None

    failure_detail: str | None = None
    contract_paths = [root / contract_rel for root in roots if (root / contract_rel).exists()]
    if not contract_paths:
        return None  # contract file gone everywhere — trust prior verification

    for contract_path in contract_paths:
        for workspace_root in roots:
            try:
                result = _run_assertions(str(contract_path), str(workspace_root))
            except (FileNotFoundError, OSError):
                continue  # unreadable contract/workspace — try other candidates
            if result.passed:
                return None
            failure_detail = "; ".join(f["detail"] for f in result.failures)
    return failure_detail


@lru_cache(maxsize=1)
def _load_openclaw_config() -> dict[str, Any]:
    """Load ~/.openclaw/openclaw.json when present."""
    config_path = Path(os.environ.get("HOME", str(Path.home()))) / ".openclaw" / "openclaw.json"
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _resolve_agent_workspace(agent_id: str | None) -> Path | None:
    """Return the configured workspace path for an agent, if known."""
    if not agent_id:
        return None
    config = _load_openclaw_config()
    agents = ((config.get("agents") or {}).get("list") or [])
    for entry in agents:
        if entry.get("id") == agent_id and entry.get("workspace"):
            return Path(entry["workspace"]).resolve()
    return None


def _mark_stalled_stages(state: dict[str, Any]) -> None:
    """Transition running stages past their stall threshold to stalled."""
    threshold = int(state.get("stall_threshold_minutes", 60))
    now = datetime.now(tz=UTC)
    for stage in state.get("stages", []):
        if stage.get("status") != "running" or not stage.get("started_at"):
            continue
        try:
            started = datetime.fromisoformat(stage["started_at"])
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue
        if (now - started).total_seconds() / 60 > threshold:
            mark_stage_stalled(state, stage["name"], actor=_ACTOR)


def _decide_next(state: dict[str, Any]) -> ResumeResponse:
    """Return the appropriate ResumeResponse based on current stage statuses."""
    max_attempts = int(state.get("max_attempts_per_stage", 2))
    guards: dict[str, Any] = state.get("guards", {})
    prior_work = _collect_prior_work(state)

    # Check for blocking conditions first: retry exhaustion halts the pipeline.
    for stage in state.get("stages", []):
        status = stage.get("status")
        attempts = int(stage.get("attempt", 0))
        if status == "stalled" and attempts >= max_attempts:
            append_audit(
                state,
                "pipeline_escalated",
                stage=stage["name"],
                actor=_ACTOR,
                detail=f"max attempts ({max_attempts}) exceeded after stall",
            )
            return ResumeResponse(
                action="escalate",
                stage=stage["name"],
                reason=f"max attempts exceeded on stage '{stage['name']}' after stall",
            )
        if status == "failed" and attempts >= max_attempts:
            append_audit(
                state,
                "pipeline_escalated",
                stage=stage["name"],
                actor=_ACTOR,
                detail=f"max attempts ({max_attempts}) exceeded",
            )
            return ResumeResponse(
                action="escalate",
                stage=stage["name"],
                reason=f"max attempts exceeded on stage '{stage['name']}'",
            )

    next_stage = _find_next_stage(state, max_attempts)

    if next_stage is None:
        return _terminal_response(state)

    # Step 6: block stages requiring fresh current-session approval.
    guard_name: str | None = next_stage.get("approval_guard")
    if guard_name and not guards.get(guard_name, False):
        append_audit(
            state,
            "pipeline_escalated",
            stage=next_stage["name"],
            actor=_ACTOR,
            detail=f"approval required for {guard_name}",
        )
        return ResumeResponse(
            action="escalate",
            stage=next_stage["name"],
            reason=f"approval required for {guard_name}",
        )

    # Steps 8-9b: mark running (increments attempt) and return resume.
    mark_stage_running(state, next_stage["name"], actor=_ACTOR)
    append_audit(state, "stage_resumed", stage=next_stage["name"], actor=_ACTOR)
    return ResumeResponse(
        action="resume",
        stage=next_stage["name"],
        agent=next_stage.get("agent"),
        contract=next_stage.get("contract"),
        prior_work=prior_work,
    )


def _find_next_stage(state: dict[str, Any], max_attempts: int) -> dict[str, Any] | None:
    """Return the first pending or retryable failed/stalled stage, or None."""
    for stage in state.get("stages", []):
        status = stage.get("status")
        if status == "pending":
            return stage
        if status in {"failed", "stalled"} and int(stage.get("attempt", 0)) < max_attempts:
            return stage
    return None


def _terminal_response(state: dict[str, Any]) -> ResumeResponse:
    """Return complete or escalate once no actionable stages remain."""
    if check_pipeline_terminal(state) == "completed":
        return ResumeResponse(action="complete")
    failed_names = [s["name"] for s in state.get("stages", []) if s.get("status") == "failed"]
    reason = (
        f"pipeline failed: max attempts exceeded on {', '.join(failed_names)}"
        if failed_names
        else "pipeline failed"
    )
    return ResumeResponse(action="escalate", reason=reason)


def _collect_prior_work(state: dict[str, Any]) -> dict[str, str]:
    """Build stage_name → artifact_path map for all completed stages with artifacts."""
    return {
        s["name"]: s["artifact"]
        for s in state.get("stages", [])
        if s.get("status") == "completed" and s.get("artifact")
    }
