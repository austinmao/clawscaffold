"""Depth mode evaluation for adopt interviews."""

from __future__ import annotations

from clawscaffold.models import ConfigFinding, DepthMode, Recommendation

_RISK_WEIGHT = {"low": 0.5, "medium": 1.5, "high": 3.0}


def _check_hard_stops(config_findings: list[ConfigFinding], recommendations: dict[str, Recommendation]) -> list[str]:
    triggers: list[str] = []
    if any(finding.confidence < 0.6 for finding in config_findings):
        triggers.append("low_confidence_gap")
    if any(finding.risk_level == "high" and finding.classification in {"missing", "inferred"} for finding in config_findings):
        triggers.append("high_risk_gap")
    if any(finding.classification == "nonstandard_gap" and finding.confidence >= 0.8 for finding in config_findings):
        triggers.append("nonstandard_gap")
    if any("conflict" in recommendation.risk_flags or recommendation.recommendation_type == "conflict_resolution" for recommendation in recommendations.values()):
        triggers.append("conflict_review")
    return triggers


def _calculate_weighted_score(config_findings: list[ConfigFinding], recommendations: dict[str, Recommendation]) -> float:
    score = 0.0
    for finding in config_findings:
        score += _RISK_WEIGHT[finding.risk_level]
        if finding.classification == "missing":
            score += 0.5
        elif finding.classification == "nonstandard_gap":
            score += 1.0
    for recommendation in recommendations.values():
        if recommendation.review_required:
            score += 0.5
        if "low_confidence" in recommendation.risk_flags:
            score += 1.0
        if "conflict" in recommendation.risk_flags:
            score += 2.0
    return round(score, 2)


def evaluate_depth_mode(
    config_findings: list[ConfigFinding],
    recommendations: dict[str, Recommendation],
    *,
    score_threshold: float = 3.0,
) -> DepthMode:
    triggers = _check_hard_stops(config_findings, recommendations)
    weighted_score = _calculate_weighted_score(config_findings, recommendations)
    if triggers:
        return DepthMode(
            mode="deep",
            hard_stop_triggers=triggers,
            weighted_score=weighted_score,
            score_threshold=score_threshold,
            transition_reason=f"Deep mode triggered by: {', '.join(triggers)}.",
        )
    if weighted_score >= score_threshold:
        return DepthMode(
            mode="deep",
            hard_stop_triggers=[],
            weighted_score=weighted_score,
            score_threshold=score_threshold,
            transition_reason="Multiple medium-risk gaps make a strategic pass safer than a fast confirmation pass.",
        )
    return DepthMode(
        mode="light",
        hard_stop_triggers=[],
        weighted_score=weighted_score,
        score_threshold=score_threshold,
        transition_reason="No hard-stop triggers fired, so the planner can batch low-risk confirmations.",
    )
