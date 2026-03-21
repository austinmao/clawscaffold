"""Single-run state machine and lock helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from clawscaffold.constants import RUN_STATES, STATE_TRANSITIONS
from clawscaffold.utils import now_iso


@dataclass
class TransitionEntry:
    from_state: str
    to_state: str
    timestamp: str
    actor: str
    notes: str = ""


@dataclass
class RunStateMachine:
    run_id: str
    state: str = "proposed"
    history: list[TransitionEntry] = field(default_factory=list)
    blocked_reason: str | None = None
    snapshot_paths: list[str] = field(default_factory=list)
    child_runs: list[str] = field(default_factory=list)
    schema_version: str = "0.1.0"
    lock_path: Path = field(default_factory=lambda: Path("compiler/.lock"))
    _lock_fd: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.state not in RUN_STATES:
            raise ValueError(f"Unknown run state: {self.state}")

    def acquire_lock(self) -> Path:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Run lock already held: {self.lock_path}") from exc
        os.write(self._lock_fd, self.run_id.encode("utf-8"))
        return self.lock_path

    def release_lock(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        if self.lock_path.exists():
            self.lock_path.unlink()

    def transition(self, new_state: str, actor: str = "compiler", notes: str = "") -> None:
        if new_state not in RUN_STATES:
            raise ValueError(f"Unknown run state: {new_state}")
        if new_state not in STATE_TRANSITIONS[self.state]:
            raise ValueError(f"Invalid transition: {self.state} -> {new_state}")
        self.history.append(
            TransitionEntry(
                from_state=self.state,
                to_state=new_state,
                timestamp=now_iso(),
                actor=actor,
                notes=notes,
            )
        )
        self.state = new_state
        if new_state != "blocked":
            self.blocked_reason = None

    def block(self, reason: str, actor: str = "compiler") -> None:
        self.transition("blocked", actor=actor, notes=reason)
        self.blocked_reason = reason

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "history": [
                {
                    "from_state": item.from_state,
                    "to_state": item.to_state,
                    "timestamp": item.timestamp,
                    "actor": item.actor,
                    "notes": item.notes,
                }
                for item in self.history
            ],
            "blocked_reason": self.blocked_reason,
            "snapshot_paths": self.snapshot_paths,
            "child_runs": self.child_runs,
            "schema_version": self.schema_version,
        }
