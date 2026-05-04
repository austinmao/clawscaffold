"""Pipeline state management for multi-agent orchestration resumption.

Provides schema validation, atomic file I/O, and state-transition helpers
for pipeline state files at memory/pipelines/<pipeline_id>/state.yaml.
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yaml
from jsonschema import Draft202012Validator

from clawscaffold.utils import now_iso

# Schema version this module manages.
_SCHEMA_VERSION = 2

# Maximum audit entries before oldest is dropped.
_AUDIT_CAP = 100

# Maximum time to wait for the per-state lock file.
_LOCK_TIMEOUT_SECONDS = 10.0

# Lazy-loaded schema cache.
_schema_cache: dict[str, Any] | None = None


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "033-pipeline-resume"
    / "contracts"
    / "pipeline-state-schema.yaml"
)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def load_schema() -> dict[str, Any]:
    """Load the pipeline state JSON Schema from specs/033-pipeline-resume/contracts/.

    Results are cached for the lifetime of the process.
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache
    try:
        raw = _SCHEMA_PATH.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except OSError as exc:
        raise FileNotFoundError(
            f"Cannot read pipeline state schema at '{_SCHEMA_PATH}': {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error in pipeline state schema: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Pipeline state schema must be a YAML mapping")
    _schema_cache = data
    return _schema_cache


def validate_state(state: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate state dict against the pipeline state schema.

    Returns:
        (valid, errors) — valid is True when errors is empty.
    """
    schema = load_schema()
    validator = Draft202012Validator(schema)
    errors = [
        f"{'.'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(state), key=lambda e: list(e.absolute_path))
    ]
    return (len(errors) == 0, errors)


def is_legacy(state: dict[str, Any]) -> bool:
    """Return True if state lacks schema_version or has schema_version < 2."""
    return int(state.get("schema_version", 0)) < _SCHEMA_VERSION


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------


def read_state(state_path: Path) -> dict[str, Any]:
    """Read and parse state.yaml from disk.

    Cleans up any stale .state.yaml.tmp file found alongside the target.

    Raises:
        FileNotFoundError: If state_path does not exist.
        ValueError: If the file is not a valid YAML mapping.
    """
    tmp_path = state_path.parent / ".state.yaml.tmp"
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        raw = state_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except OSError as exc:
        raise FileNotFoundError(
            f"Cannot read state file '{state_path}': {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error in '{state_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"State file '{state_path}' must be a YAML mapping")
    return data


def write_state(state_path: Path, state: dict[str, Any]) -> None:
    """Atomically write state to disk via temp file + os.replace().

    Updates updated_at to the current UTC timestamp before writing.
    Creates parent directories if they do not exist.
    """
    state["updated_at"] = now_iso()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.parent / ".state.yaml.tmp"
    try:
        tmp_path.write_text(
            yaml.safe_dump(state, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        os.replace(tmp_path, state_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


@contextmanager
def _locked_state_file(
    state_path: Path,
    *,
    timeout_seconds: float = _LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire an exclusive lock for a pipeline state file."""
    lock_path = state_path.parent / ".state.yaml.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out acquiring pipeline state lock for '{state_path}'")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


# ---------------------------------------------------------------------------
# Stage lookup
# ---------------------------------------------------------------------------


def find_stage(
    state: dict[str, Any],
    *,
    agent: str | None = None,
    contract: str | None = None,
) -> dict[str, Any] | None:
    """Return the first stage matching the given agent ID and/or contract path.

    At least one of agent or contract must be provided.
    Returns None if no matching stage is found.
    """
    for stage in state.get("stages", []):
        agent_match = agent is None or stage.get("agent") == agent
        contract_match = contract is None or stage.get("contract") == contract
        if agent_match and contract_match:
            return stage
    return None


# ---------------------------------------------------------------------------
# State transition helpers
# ---------------------------------------------------------------------------


def mark_stage_running(
    state: dict[str, Any],
    stage_name: str,
    *,
    actor: str,
) -> None:
    """Set stage status=running, record started_at, increment attempt.

    Also transitions the pipeline status to in_progress if it is pending or stalled.
    Appends a stage_started audit entry.
    """
    stage = _require_stage(state, stage_name)
    stage["status"] = "running"
    stage["started_at"] = now_iso()
    stage["attempt"] = int(stage.get("attempt", 0)) + 1
    if state.get("status") in {"pending", "stalled"}:
        state["status"] = "in_progress"
    append_audit(state, "stage_started", stage=stage_name, actor=actor)


def mark_stage_completed(
    state: dict[str, Any],
    stage_name: str,
    *,
    actor: str,
    artifact: str | None = None,
    verification: str = "pass",
) -> None:
    """Set stage status=completed, record completed_at and verification result.

    Optionally records an artifact path. Appends a stage_completed audit entry.
    """
    stage = _require_stage(state, stage_name)
    stage["status"] = "completed"
    stage["completed_at"] = now_iso()
    stage["verification"] = verification
    if artifact is not None:
        stage["artifact"] = artifact
    append_audit(state, "stage_completed", stage=stage_name, actor=actor)


def mark_stage_failed(
    state: dict[str, Any],
    stage_name: str,
    *,
    actor: str,
    error_detail: str,
    verification: str = "fail",
) -> None:
    """Set stage status=failed, record completed_at, error_detail, and verification.

    Appends a stage_failed audit entry with the error_detail as the detail field.
    """
    stage = _require_stage(state, stage_name)
    stage["status"] = "failed"
    stage["completed_at"] = now_iso()
    stage["verification"] = verification
    stage["error_detail"] = error_detail
    append_audit(state, "stage_failed", stage=stage_name, actor=actor, detail=error_detail)


def mark_stage_stalled(
    state: dict[str, Any],
    stage_name: str,
    *,
    actor: str,
) -> None:
    """Set stage status=stalled and append a stage_stalled audit entry."""
    stage = _require_stage(state, stage_name)
    stage["status"] = "stalled"
    if state.get("status") == "in_progress":
        state["status"] = "stalled"
    append_audit(state, "stage_stalled", stage=stage_name, actor=actor)


def update_stage_verdict(
    state_path: Path,
    *,
    agent: str | None,
    contract: str | None,
    actor: str,
    passed: bool,
    artifact: str | None = None,
    error_detail: str | None = None,
) -> bool:
    """Atomically apply a plugin verdict to one stage and persist the state."""
    return _update_stage_verdict_locked(
        state_path,
        agent=agent,
        contract=contract,
        actor=actor,
        passed=passed,
        artifact=artifact,
        error_detail=error_detail,
    )


# ---------------------------------------------------------------------------
# Guard and audit helpers
# ---------------------------------------------------------------------------


def reset_guards(state: dict[str, Any]) -> None:
    """Reset all guards to False.

    Called on resume after a session boundary, ensuring no external-write
    approvals carry over from a prior session.
    """
    guards: dict[str, Any] = state.get("guards", {})
    for key in guards:
        guards[key] = False


def append_audit(
    state: dict[str, Any],
    event: str,
    *,
    stage: str | None = None,
    actor: str,
    detail: str | None = None,
) -> None:
    """Append a structured audit entry to the pipeline audit log.

    Caps the log at 100 entries by dropping the oldest when the limit is exceeded.
    """
    entry: dict[str, Any] = {
        "timestamp": now_iso(),
        "event": event,
        "actor": actor,
    }
    if stage is not None:
        entry["stage"] = stage
    if detail is not None:
        entry["detail"] = detail

    audit: list[dict[str, Any]] = state.setdefault("audit", [])
    audit.append(entry)
    if len(audit) > _AUDIT_CAP:
        state["audit"] = audit[-_AUDIT_CAP:]


# ---------------------------------------------------------------------------
# Pipeline terminal check
# ---------------------------------------------------------------------------


def check_pipeline_terminal(state: dict[str, Any]) -> str | None:
    """Return 'completed' or 'failed' when all stages are in a terminal status.

    Terminal statuses are completed, skipped, and failed.
    Returns None if any stage is still pending, running, or stalled.
    """
    _TERMINAL = frozenset({"completed", "skipped", "failed"})
    stages: list[dict[str, Any]] = state.get("stages", [])
    if not stages:
        return None
    if any(s.get("status") not in _TERMINAL for s in stages):
        return None
    if any(s.get("status") == "failed" for s in stages):
        return "failed"
    return "completed"


# ---------------------------------------------------------------------------
# State initializer
# ---------------------------------------------------------------------------


def initialize_state(
    pipeline_id: str,
    pipeline_type: str,
    orchestrator: str,
    stages: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
    guards: dict[str, bool] | None = None,
    stall_threshold_minutes: int = 60,
    max_attempts_per_stage: int = 2,
) -> dict[str, Any]:
    """Create a fresh v2 pipeline state dict with all stages pending.

    Args:
        pipeline_id: Unique identifier matching the pattern <type>-YYYY-MM-DD-<slug>.
        pipeline_type: One of newsletter, campaign, or website.
        orchestrator: Agent ID of the owning orchestrator.
        stages: List of stage dicts (at minimum each must have a 'name' key).
        context: Optional pipeline-type-specific context fields.
        guards: Optional initial guard values (defaults all False).
        stall_threshold_minutes: Minutes before a running stage is considered stalled.
        max_attempts_per_stage: Maximum retries before escalation.

    Returns:
        A fully populated state dict ready to be written with write_state().
    """
    now = now_iso()
    normalized_stages = [_normalize_stage(s) for s in stages]
    state: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "pipeline_id": pipeline_id,
        "pipeline_type": pipeline_type,
        "orchestrator": orchestrator,
        "created_at": now,
        "updated_at": now,
        "status": "pending",
        "context": context or {},
        "guards": guards or {},
        "stages": normalized_stages,
        "stall_threshold_minutes": stall_threshold_minutes,
        "max_attempts_per_stage": max_attempts_per_stage,
        "audit": [],
    }

    return state


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _require_stage(state: dict[str, Any], stage_name: str) -> dict[str, Any]:
    """Return the stage dict for stage_name or raise ValueError."""
    for stage in state.get("stages", []):
        if stage.get("name") == stage_name:
            return stage
    raise ValueError(f"Stage '{stage_name}' not found in pipeline '{state.get('pipeline_id')}'")


def _normalize_stage(stage: dict[str, Any]) -> dict[str, Any]:
    """Return a stage dict with all required fields populated at pending defaults."""
    return {
        "name": stage["name"],
        "status": stage.get("status", "pending"),
        "agent": stage.get("agent"),
        "contract": stage.get("contract"),
        "approval_guard": stage.get("approval_guard"),
        "artifact": stage.get("artifact"),
        "started_at": stage.get("started_at"),
        "completed_at": stage.get("completed_at"),
        "verification": stage.get("verification"),
        "error_detail": stage.get("error_detail"),
        "attempt": stage.get("attempt", 0),
    }


def _update_stage_verdict_locked(
    state_path: Path,
    *,
    agent: str | None,
    contract: str | None,
    actor: str,
    passed: bool,
    artifact: str | None,
    error_detail: str | None,
    delay_after_read_seconds: float = 0.0,
) -> bool:
    """Internal locked stage update helper shared by plugin tests and runtime."""
    with _locked_state_file(state_path):
        state = read_state(state_path)
        if delay_after_read_seconds > 0:
            time.sleep(delay_after_read_seconds)

        stage = find_stage(state, agent=agent, contract=contract)
        if stage is None:
            return False

        if passed:
            mark_stage_completed(
                state,
                stage["name"],
                actor=actor,
                verification="pass",
                artifact=artifact,
            )
        else:
            if artifact is not None:
                stage["artifact"] = artifact
            mark_stage_failed(
                state,
                stage["name"],
                actor=actor,
                error_detail=error_detail or "contract verification failed",
            )

        term = check_pipeline_terminal(state)
        if term:
            event = "pipeline_completed" if term == "completed" else "pipeline_failed"
            append_audit(state, event, actor=actor)
            state["status"] = term

        write_state(state_path, state)
        return True
