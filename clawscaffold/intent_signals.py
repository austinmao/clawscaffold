"""Session-scoped soft intent tracking for adopt interviews."""

from __future__ import annotations

from clawscaffold.models import IntentSignal
from clawscaffold.utils import now_iso

_SIGNAL_TYPES = (
    "preservation_first",
    "prefers_minimal_interruption",
    "wants_explicit_config",
    "low_autonomy_preference",
)


class IntentSignalTracker:
    def __init__(self, signals: list[IntentSignal] | None = None) -> None:
        baseline = {signal.signal_type: signal.confidence for signal in (signals or [])}
        self._confidence = {signal_type: float(baseline.get(signal_type, 0.0)) for signal_type in _SIGNAL_TYPES}
        self._updated_at = {signal_type: now_iso() for signal_type in _SIGNAL_TYPES}

    def _apply_delta(self, signal_type: str, delta: float) -> None:
        value = max(0.0, min(1.0, self._confidence[signal_type] + delta))
        self._confidence[signal_type] = round(value, 3)
        self._updated_at[signal_type] = now_iso()

    def update(self, question_id: str, answer_type: str, answer_value: object | None = None) -> None:
        normalized = str(answer_type or "").lower()
        if normalized in {"keep", "confirm_all"} or question_id.startswith("section.") and normalized == "accept":
            self._apply_delta("preservation_first", 0.2)
        if normalized in {"accept", "confirm_all"}:
            self._apply_delta("prefers_minimal_interruption", 0.2)
        if normalized in {"override", "edit", "review", "review_individually"}:
            self._apply_delta("wants_explicit_config", 0.2)
        if normalized in {"override", "edit"}:
            self._apply_delta("preservation_first", -0.15)
            self._apply_delta("prefers_minimal_interruption", -0.15)

        value_text = str(answer_value or "").lower()
        if "confirm" in value_text or "manual" in value_text or "approval" in value_text:
            self._apply_delta("low_autonomy_preference", 0.2)

    def get_active_signals(self) -> list[IntentSignal]:
        return [signal for signal in self.get_all_signals() if signal.active]

    def get_all_signals(self) -> list[IntentSignal]:
        return [
            IntentSignal(
                signal_type=signal_type,
                confidence=self._confidence[signal_type],
                active=self._confidence[signal_type] >= 0.5,
                last_updated_at=self._updated_at[signal_type],
            )
            for signal_type in _SIGNAL_TYPES
        ]
