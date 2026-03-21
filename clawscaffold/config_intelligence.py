"""Adopt-only config gap detection and decision bundling."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from clawscaffold.models import ConfigFinding, DecisionBundle, SectionContent
from clawscaffold.utils import canonical_target_path, deep_merge, read_yaml

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_SCHEDULING_PATTERN = re.compile(
    r"\b(heartbeat|check every|every \d+ (minute|minutes|hour|hours|day|days)|daily|weekly|cron|monitor)\b",
    re.IGNORECASE,
)

# --- Pass 2 inference helpers (prose patterns) ---

_ORG_MANAGEMENT_PATTERN = re.compile(
    r"\b(coordinate|delegate|manage|oversee|orchestrate)\b",
    re.IGNORECASE,
)
_SUB_AGENT_REF_PATTERN = re.compile(
    r"I\s+(?:coordinate|manage|oversee|delegate\s+to)\s+([a-z][a-z0-9\-,\s]+)",
    re.IGNORECASE,
)
_ESCALATION_PROSE_PATTERN = re.compile(
    r"\b(escalate\s+to|handoff\s+to|notify\s+operator|hand\s+off\s+to)\b",
    re.IGNORECASE,
)
_COLLABORATION_PATTERN = re.compile(
    r"\b(collaborate\s+with|work\s+alongside|peer\s+with)\b",
    re.IGNORECASE,
)

# --- Resource limit tier table (budget_tier -> limits) ---

_RESOURCE_TIER_TABLE: dict[str, dict[str, int]] = {
    "economy": {
        "max_tokens_per_session": 10_000,
        "max_sessions_per_day": 20,
        "max_outbound_per_day": 5,
    },
    "standard": {
        "max_tokens_per_session": 50_000,
        "max_sessions_per_day": 100,
        "max_outbound_per_day": 50,
    },
    "premium": {
        "max_tokens_per_session": 200_000,
        "max_sessions_per_day": 500,
        "max_outbound_per_day": 200,
    },
}

# --- Observability tier table (risk_tier -> observability) ---

_OBSERVABILITY_TIER_TABLE: dict[str, dict[str, Any]] = {
    "low": {
        "log_level": "minimal",
        "cost_tracking": False,
        "alert_on_failure": False,
        "paperclip_sync": False,
    },
    "medium": {
        "log_level": "standard",
        "cost_tracking": True,
        "alert_on_failure": False,
        "paperclip_sync": True,
    },
    "high": {
        "log_level": "verbose",
        "cost_tracking": True,
        "alert_on_failure": True,
        "paperclip_sync": True,
    },
}

_BUNDLE_SPECS: dict[str, dict[str, Any]] = {
    # --- Existing 4 bundles (Pass 1) ---
    "cognition_posture": {
        "display_name": "Cognition Posture",
        "description": "Reasoning depth, cost posture, and risk posture",
        "schema_path": "policy.cognition",
        "risk_level": "medium",
        "blocking_level": "stabilizing",
        "pass_number": 1,
    },
    "operational_autonomy": {
        "display_name": "Operational Autonomy",
        "description": "Approval posture and execution freedom",
        "schema_path": "operation.approvals",
        "risk_level": "high",
        "blocking_level": "blocking",
        "pass_number": 1,
    },
    "cadence_monitoring": {
        "display_name": "Cadence and Monitoring",
        "description": "Heartbeat cadence and recurring monitoring behavior",
        "schema_path": "agent.heartbeat",
        "risk_level": "medium",
        "blocking_level": "quality",
        "pass_number": 2,
    },
    "memory_persistence": {
        "display_name": "Memory and Persistence",
        "description": "Memory retrieval posture and persistence expectations",
        "schema_path": "policy.memory",
        "risk_level": "medium",
        "blocking_level": "stabilizing",
        "pass_number": 1,
    },
    # --- 8 new bundles ---
    "org_hierarchy": {
        "display_name": "Organizational Hierarchy",
        "description": "Reporting structure, org level, and management relationships",
        "schema_path": "org",
        "risk_level": "high",
        "blocking_level": "blocking",
        "pass_number": 1,
    },
    "data_classification": {
        "display_name": "Data Classification",
        "description": "Data sensitivity, PII/PHI handling, and retention policy",
        "schema_path": "policy.compliance",
        "risk_level": "high",
        "blocking_level": "blocking",
        "pass_number": 1,
    },
    "scheduling_constraints": {
        "display_name": "Scheduling Constraints",
        "description": "Quiet hours, concurrency limits, and SLA response times",
        "schema_path": "operation.scheduling",
        "risk_level": "low",
        "blocking_level": "stabilizing",
        "pass_number": 1,
    },
    "coordination_pattern": {
        "display_name": "Coordination Pattern",
        "description": "Standalone, orchestrator, worker, or peer coordination mode",
        "schema_path": "operation.coordination",
        "risk_level": "high",
        "blocking_level": "stabilizing",
        "pass_number": 2,
    },
    "escalation_chain": {
        "display_name": "Escalation Chain",
        "description": "Ordered escalation path and timeout behavior",
        "schema_path": "operation.escalation",
        "risk_level": "medium",
        "blocking_level": "stabilizing",
        "pass_number": 2,
    },
    "resource_limits": {
        "display_name": "Resource Limits",
        "description": "Token, session, and outbound rate limits per budget tier",
        "schema_path": "policy.resource_limits",
        "risk_level": "medium",
        "blocking_level": "quality",
        "pass_number": 2,
    },
    "observability_posture": {
        "display_name": "Observability Posture",
        "description": "Logging level, cost tracking, alerting, and Paperclip sync",
        "schema_path": "policy.observability",
        "risk_level": "low",
        "blocking_level": "quality",
        "pass_number": 2,
    },
    "resilience_pattern": {
        "display_name": "Resilience Pattern",
        "description": "Fallback agent, degraded mode, and circuit breaker threshold",
        "schema_path": "operation.resilience",
        "risk_level": "medium",
        "blocking_level": "quality",
        "pass_number": 2,
    },
}


def _path_value(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _canonical_spec(kind: str, target_id: str, root: Path) -> dict[str, Any]:
    path = canonical_target_path(kind, target_id, root)
    if not path.exists():
        return {}
    return read_yaml(path)


def _combined_text(sections: dict[str, SectionContent]) -> str:
    return "\n".join(section.content for section in sections.values())


def _default_patch(bundle_id: str, kind: str, target_id: str) -> dict[str, Any]:
    department = target_id.split("/", 1)[0] if "/" in target_id else target_id
    if bundle_id == "cognition_posture":
        if kind == "skill":
            return {"policy": {"cognition": {"complexity": "low", "cost_posture": "economy", "risk_posture": "low"}}}
        complexity = "high" if department in {"security", "finance"} else "medium"
        return {"policy": {"cognition": {"complexity": complexity, "cost_posture": "standard", "risk_posture": "low"}}}
    if bundle_id == "operational_autonomy":
        return {"operation": {"approvals": {"default": "confirm"}}}
    if bundle_id == "cadence_monitoring":
        return {"agent": {"heartbeat": {"enabled": True, "cadence_minutes": 60, "checklist": []}}}
    if bundle_id == "memory_persistence":
        interaction_mode = "read" if kind == "skill" else "read_write"
        return {
            "policy": {
                "memory": {
                    "retrieval_mode": "universal_file",
                    "namespaces": ["shared"],
                    "write_permitted": kind == "agent",
                    "fallback_behavior": "file_only",
                    "routing_compatible": True,
                    "interaction_mode": interaction_mode,
                }
            }
        }
    if bundle_id == "org_hierarchy":
        return {"org": {"reports_to": None, "org_level": "ic", "manages": []}}
    if bundle_id == "data_classification":
        return {
            "policy": {
                "compliance": {
                    "data_classification": "internal",
                    "handles_pii": False,
                    "handles_phi": False,
                    "retention_days": 90,
                }
            }
        }
    if bundle_id == "scheduling_constraints":
        return {
            "operation": {
                "scheduling": {
                    "quiet_hours": None,
                    "max_concurrent": 1,
                    "sla_response_seconds": 3600,
                }
            }
        }
    if bundle_id == "coordination_pattern":
        return {
            "operation": {
                "coordination": {
                    "pattern": "standalone",
                    "can_spawn": False,
                    "max_spawn_depth": 0,
                }
            }
        }
    if bundle_id == "escalation_chain":
        return {
            "operation": {
                "escalation": {
                    "chain": ["operator"],
                    "timeout_seconds": 300,
                    "fallback_behavior": "escalate",
                }
            }
        }
    if bundle_id == "resource_limits":
        return {
            "policy": {
                "resource_limits": dict(_RESOURCE_TIER_TABLE["standard"]),
            }
        }
    if bundle_id == "observability_posture":
        return {
            "policy": {
                "observability": dict(_OBSERVABILITY_TIER_TABLE["medium"]),
            }
        }
    if bundle_id == "resilience_pattern":
        return {
            "operation": {
                "resilience": {
                    "fallback_agent": None,
                    "circuit_breaker_threshold": 3,
                }
            }
        }
    return {}


def _default_recommendation(bundle_id: str, kind: str, target_id: str) -> str:
    department = target_id.split("/", 1)[0] if "/" in target_id else target_id
    if bundle_id == "cognition_posture":
        if kind == "skill":
            return "Use a low-complexity, economy-cost posture unless this skill needs multi-step reasoning."
        return f"Use a medium-complexity posture for {department} unless this target handles high-risk review."
    if bundle_id == "operational_autonomy":
        return "Keep approvals explicit so live actions still require operator confirmation."
    if bundle_id == "cadence_monitoring":
        return "Add an explicit heartbeat only if this target is expected to monitor or check in on a schedule."
    if bundle_id == "memory_persistence":
        return "Declare retrieval mode explicitly so memory use is reviewable instead of implied by prose."
    if bundle_id == "org_hierarchy":
        return "Declare reporting structure so delegation authority and escalation routing are machine-resolvable."
    if bundle_id == "data_classification":
        return "Declare data classification so compliance controls are applied automatically."
    if bundle_id == "scheduling_constraints":
        return "Declare scheduling constraints so quiet hours and concurrency limits are enforced."
    if bundle_id == "coordination_pattern":
        return "Declare coordination pattern so spawn authority and handoff contracts are enforced."
    if bundle_id == "escalation_chain":
        return "Declare escalation chain so failures route to the correct handler."
    if bundle_id == "resource_limits":
        return "Declare resource limits so token and session budgets are enforced per budget tier."
    if bundle_id == "observability_posture":
        return "Declare observability posture so logging and alerting match the risk tier."
    if bundle_id == "resilience_pattern":
        return "Declare resilience pattern so circuit breakers and fallback agents are configured."
    return "Document this configuration explicitly."


def _check_schema_support(dimension: str, kind: str) -> bool:
    if dimension == "cadence_monitoring":
        return kind == "agent"
    return dimension in _BUNDLE_SPECS


def _infer_dimension_value(
    dimension: str,
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
) -> tuple[Any, str | None, float]:
    combined = _combined_text(sections)
    if dimension == "cognition_posture":
        cognition = dict(policy_hints.get("cognition", {}))
        if cognition.get("complexity"):
            return cognition, "target_inference", 0.75
    if dimension == "operational_autonomy":
        approvals = list(policy_hints.get("approvals", []))
        if approvals:
            return {"approvals": approvals}, "target_inference", 0.7
        if "explicit approval" in combined.lower():
            return {"approvals": ["confirm"]}, "target_inference", 0.65
    if dimension == "cadence_monitoring":
        if _SCHEDULING_PATTERN.search(combined):
            inferred = {"cadence_signal": _SCHEDULING_PATTERN.search(combined).group(1)}
            basis = "target_inference" if kind == "agent" else "design_prompt"
            confidence = 0.75 if kind == "agent" else 0.85
            return inferred, basis, confidence
    if dimension == "memory_persistence":
        memory = dict(policy_hints.get("memory", {}))
        if memory.get("retrieval_mode"):
            return memory, "target_inference", 0.8
        if policy_hints.get("memory_paths"):
            return {"memory_paths": list(policy_hints["memory_paths"])}, "target_inference", 0.65
    # --- New bundle inference cases ---
    if dimension == "org_hierarchy":
        return _infer_org_hierarchy(kind, policy_hints, sections, combined)
    if dimension == "data_classification":
        return _infer_data_classification(kind, policy_hints, sections, combined)
    if dimension == "scheduling_constraints":
        return _infer_scheduling_constraints(kind, policy_hints, sections, combined)
    if dimension == "coordination_pattern":
        return _infer_coordination_pattern(kind, policy_hints, sections, combined)
    if dimension == "escalation_chain":
        return _infer_escalation_chain(kind, policy_hints, sections, combined)
    if dimension == "resource_limits":
        return _infer_resource_limits(kind, policy_hints, sections, combined)
    if dimension == "observability_posture":
        return _infer_observability_posture(kind, policy_hints, sections, combined)
    if dimension == "resilience_pattern":
        return _infer_resilience_pattern(kind, policy_hints, sections, combined)
    return None, None, 0.0


def _infer_org_hierarchy(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    target_id = policy_hints.get("_target_id", "")
    result: dict[str, Any] = {}

    # Check for sub-agent references in prose
    sub_agent_match = _SUB_AGENT_REF_PATTERN.search(combined)
    if sub_agent_match:
        raw_refs = sub_agent_match.group(1)
        manages = [ref.strip() for ref in raw_refs.split(",") if ref.strip()]
        result["manages"] = manages
        result["org_level"] = "manager"
        return result, "target_inference", 0.75

    # Check management prose patterns
    if _ORG_MANAGEMENT_PATTERN.search(combined):
        result["org_level"] = "manager"
        result["manages"] = []
        return result, "target_inference", 0.75

    # Check agent name patterns
    name_part = target_id.rsplit("/", 1)[-1] if "/" in target_id else target_id
    if name_part in ("orchestrator", "coordinator", "director"):
        result["org_level"] = "manager"
        result["manages"] = []
        return result, "target_inference", 0.75

    # Check domain for utility tier
    department = target_id.split("/", 1)[0] if "/" in target_id else target_id
    if department == "platform":
        result["org_level"] = "utility"
        result["manages"] = []
        return result, "target_inference", 0.75

    return None, None, 0.0


def _infer_data_classification(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    target_id = policy_hints.get("_target_id", "")
    department = target_id.split("/", 1)[0] if "/" in target_id else target_id
    name_part = target_id.rsplit("/", 1)[-1] if "/" in target_id else target_id
    combined_lower = combined.lower()

    # Domain programs/ + medical keyword
    if department == "programs" and "medical" in name_part:
        return {
            "data_classification": "restricted",
            "handles_pii": True,
            "handles_phi": True,
            "retention_days": 365,
        }, "target_inference", 0.9

    # CRM integration or side effects
    integrations = policy_hints.get("integrations", [])
    side_effects = policy_hints.get("side_effects", [])
    if "crm" in [i.lower() for i in integrations] or "modify_crm" in side_effects:
        return {
            "data_classification": "confidential",
            "handles_pii": True,
            "handles_phi": False,
            "retention_days": 90,
        }, "target_inference", 0.9

    # Prose mentions of PII/PHI
    if "pii" in combined_lower or "personal data" in combined_lower or "personally identifiable" in combined_lower:
        return {
            "data_classification": "confidential",
            "handles_pii": True,
            "handles_phi": False,
            "retention_days": 90,
        }, "target_inference", 0.75

    if "phi" in combined_lower or "protected health" in combined_lower or "medical record" in combined_lower:
        return {
            "data_classification": "restricted",
            "handles_pii": True,
            "handles_phi": True,
            "retention_days": 365,
        }, "target_inference", 0.75

    # Read-only / internal write side effects
    if side_effects and all(se in ("read_only", "internal_write") for se in side_effects):
        return {
            "data_classification": "internal",
            "handles_pii": False,
            "handles_phi": False,
            "retention_days": 90,
        }, "target_inference", 0.7

    # External audience + publish
    audience = policy_hints.get("audience", "")
    if audience == "external" and "publish_content" in side_effects:
        return {
            "data_classification": "public",
            "handles_pii": False,
            "handles_phi": False,
            "retention_days": 90,
        }, "target_inference", 0.7

    return None, None, 0.0


def _infer_scheduling_constraints(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    result: dict[str, Any] = {}
    inferred = False

    # Check heartbeat active_hours for quiet hours inversion
    heartbeat = policy_hints.get("heartbeat", {})
    active_hours = heartbeat.get("active_hours") if isinstance(heartbeat, dict) else None
    if active_hours and isinstance(active_hours, dict):
        # Invert active hours to quiet hours
        result["quiet_hours"] = {
            "start": active_hours.get("end", "21:00"),
            "end": active_hours.get("start", "08:00"),
            "timezone": active_hours.get("timezone", "UTC"),
        }
        inferred = True

    # Check channels for external audience -> quiet hours
    channels = policy_hints.get("channels", [])
    if isinstance(channels, list):
        for channel in channels:
            if isinstance(channel, dict):
                ch_type = channel.get("type", "")
                audience = channel.get("audience", "")
                if ch_type in ("whatsapp", "imessage") and audience == "external":
                    if "quiet_hours" not in result:
                        result["quiet_hours"] = {"start": "21:00", "end": "08:00"}
                    inferred = True
                    break

    # Determine SLA based on audience
    audience = policy_hints.get("audience", "")
    if audience == "external":
        result["sla_response_seconds"] = 300
        inferred = True
    elif audience == "internal":
        result["sla_response_seconds"] = 3600
        inferred = True

    # Orchestrators get higher concurrency
    target_id = policy_hints.get("_target_id", "")
    name_part = target_id.rsplit("/", 1)[-1] if "/" in target_id else target_id
    if name_part in ("orchestrator", "coordinator", "director"):
        result["max_concurrent"] = 3
        inferred = True

    if inferred:
        return result, "target_inference", 0.75

    return None, None, 0.0


def _infer_coordination_pattern(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    # Read org_hierarchy output from the merged spec (passed via policy_hints for Pass 2)
    org = policy_hints.get("org", {})
    manages = org.get("manages", []) if isinstance(org, dict) else []
    org_level = org.get("org_level", "") if isinstance(org, dict) else ""

    # Has manages[] populated -> orchestrator
    if manages:
        return {
            "pattern": "orchestrator",
            "can_spawn": True,
            "max_spawn_depth": 2,
        }, "target_inference", 0.8

    # Listed in another's manages[] (indicated by org_level = worker or by policy hint)
    if policy_hints.get("_is_managed"):
        return {
            "pattern": "worker",
            "can_spawn": False,
            "max_spawn_depth": 0,
        }, "target_inference", 0.8

    # Collaboration prose
    if _COLLABORATION_PATTERN.search(combined):
        return {
            "pattern": "peer",
            "can_spawn": False,
            "max_spawn_depth": 0,
        }, "target_inference", 0.6

    # Manager org_level without explicit manages[] (inferred from name/prose)
    if org_level == "manager":
        return {
            "pattern": "orchestrator",
            "can_spawn": True,
            "max_spawn_depth": 2,
        }, "target_inference", 0.6

    return None, None, 0.0


def _infer_escalation_chain(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    chain: list[str] = []

    # reports_to from org_hierarchy output (via merged spec)
    org = policy_hints.get("org", {})
    reports_to = org.get("reports_to") if isinstance(org, dict) else None
    if reports_to:
        chain.append(reports_to)

    # Prose-based escalation targets
    if _ESCALATION_PROSE_PATTERN.search(combined) and not chain:
        # Found escalation prose but specific targets require more context
        chain.append("operator")

    # Always append operator as terminal if not already present
    if chain and chain[-1] != "operator":
        chain.append("operator")

    if chain:
        return {
            "chain": chain,
            "timeout_seconds": 300,
            "fallback_behavior": "escalate",
        }, "target_inference", 0.7

    return None, None, 0.0


def _infer_resource_limits(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    governance = policy_hints.get("governance", {})
    budget_tier = governance.get("budget_tier") if isinstance(governance, dict) else None
    if budget_tier and budget_tier in _RESOURCE_TIER_TABLE:
        return dict(_RESOURCE_TIER_TABLE[budget_tier]), "target_inference", 0.85

    return None, None, 0.0


def _infer_observability_posture(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    governance = policy_hints.get("governance", {})
    risk_tier = governance.get("risk_tier") if isinstance(governance, dict) else None
    if risk_tier and risk_tier in _OBSERVABILITY_TIER_TABLE:
        return dict(_OBSERVABILITY_TIER_TABLE[risk_tier]), "target_inference", 0.9

    return None, None, 0.0


def _infer_resilience_pattern(
    kind: str,
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent],
    combined: str,
) -> tuple[Any, str | None, float]:
    # Read coordination_pattern output from merged spec (Pass 2)
    coordination = policy_hints.get("operation", {})
    coord_block = coordination.get("coordination", {}) if isinstance(coordination, dict) else {}
    pattern = coord_block.get("pattern", "") if isinstance(coord_block, dict) else ""

    # Read escalation chain output from merged spec (Pass 2)
    esc_block = coordination.get("escalation", {}) if isinstance(coordination, dict) else {}
    esc_chain = esc_block.get("chain", []) if isinstance(esc_block, dict) else []

    result: dict[str, Any] = {}

    if pattern == "orchestrator":
        result["circuit_breaker_threshold"] = 3
        result["fallback_agent"] = None
    elif pattern == "worker":
        result["circuit_breaker_threshold"] = 2
        result["degraded_mode"] = "Report failure to orchestrator"
    elif pattern == "standalone":
        result["circuit_breaker_threshold"] = 3
        result["fallback_agent"] = "operator"
    elif pattern:
        result["circuit_breaker_threshold"] = 3
        result["fallback_agent"] = None

    # If escalation chain has entries, use first as fallback
    if esc_chain and len(esc_chain) > 0:
        result["fallback_agent"] = esc_chain[0]

    if result:
        return result, "target_inference", 0.8

    return None, None, 0.0


def _reason_for(dimension: str, classification: str, kind: str) -> str:
    if dimension == "cognition_posture":
        if classification == "missing":
            return "No explicit cognition posture is declared. That leaves reasoning depth and cost posture implicit."
        if classification == "inferred":
            return "Cognition posture is implied by runtime instructions but not declared in the canonical target."
    if dimension == "operational_autonomy":
        if classification == "missing":
            return "Approval posture is not explicit. That changes how aggressively the target may act."
        if classification == "inferred":
            return "Approval posture is implied in prose but not locked into configuration."
    if dimension == "cadence_monitoring":
        if classification == "missing":
            return "Recurring monitoring appears expected, but heartbeat cadence is not configured explicitly."
        if classification == "nonstandard_gap":
            return f"{kind.capitalize()} targets do not support heartbeat cadence in schema, so this must stay advisory."
    if dimension == "memory_persistence":
        if classification == "missing":
            return "Memory behavior is not explicit. Operators cannot tell whether retrieval is optional, required, or disabled."
        if classification == "inferred":
            return "Memory behavior is implied by the runtime content but not captured canonically."
    # --- New bundle reason strings ---
    if dimension == "org_hierarchy":
        if classification == "missing":
            return "No organizational hierarchy is declared. Delegation authority and escalation routing cannot be resolved."
        if classification == "inferred":
            return "Organizational hierarchy is implied by prose patterns but not locked into configuration."
    if dimension == "data_classification":
        if classification == "missing":
            return "Data classification is not declared. Compliance controls cannot be applied automatically."
        if classification == "inferred":
            return "Data sensitivity is implied by domain or integrations but not declared in the canonical target."
    if dimension == "scheduling_constraints":
        if classification == "missing":
            return "No scheduling constraints are declared. Quiet hours and concurrency limits are not enforced."
        if classification == "inferred":
            return "Scheduling constraints are implied by channel configuration but not declared explicitly."
    if dimension == "coordination_pattern":
        if classification == "missing":
            return "No coordination pattern is declared. Spawn authority and handoff contracts are not enforced."
        if classification == "inferred":
            return "Coordination pattern is implied by hierarchy output but not locked into configuration."
    if dimension == "escalation_chain":
        if classification == "missing":
            return "No escalation chain is declared. Failures have no defined routing path."
        if classification == "inferred":
            return "Escalation chain is implied by hierarchy and prose but not declared in configuration."
    if dimension == "resource_limits":
        if classification == "missing":
            return "No resource limits are declared. Token and session budgets are not enforced."
        if classification == "inferred":
            return "Resource limits are derived from budget tier but not declared explicitly."
    if dimension == "observability_posture":
        if classification == "missing":
            return "No observability posture is declared. Logging and alerting behavior is undefined."
        if classification == "inferred":
            return "Observability posture is derived from risk tier but not declared explicitly."
    if dimension == "resilience_pattern":
        if classification == "missing":
            return "No resilience pattern is declared. Circuit breakers and fallback agents are not configured."
        if classification == "inferred":
            return "Resilience pattern is derived from coordination and escalation output but not declared explicitly."
    return "This configuration decision affects runtime behavior and should be reviewed explicitly."


def _classify_dimension(
    dimension: str,
    kind: str,
    canonical_spec: dict[str, Any],
    policy_hints: dict[str, Any],
    sections: dict[str, SectionContent] | None = None,
) -> ConfigFinding:
    section_map = sections or {}
    bundle_spec = _BUNDLE_SPECS[dimension]
    risk_level = bundle_spec["risk_level"]
    if dimension == "operational_autonomy" and kind == "skill":
        risk_level = "medium"
    schema_path = bundle_spec["schema_path"] if _check_schema_support(dimension, kind) else None
    explicit_value = _path_value(canonical_spec, schema_path) if schema_path else None
    if explicit_value not in (None, {}, []):
        return ConfigFinding(
            dimension=dimension,
            bundle=dimension,
            classification="explicit",
            confidence=1.0,
            risk_level=risk_level,
            schema_path=schema_path,
            explicit_value=explicit_value,
            question_reason=_reason_for(dimension, "explicit", kind),
        )

    inferred_value, inference_basis, confidence = _infer_dimension_value(dimension, kind, policy_hints, section_map)
    if inferred_value is not None:
        classification = "inferred"
        if dimension == "cadence_monitoring" and not _check_schema_support(dimension, kind):
            classification = "nonstandard_gap"
            schema_path = None
        return ConfigFinding(
            dimension=dimension,
            bundle=dimension,
            classification=classification,
            confidence=confidence,
            risk_level=risk_level,
            schema_path=schema_path,
            inferred_value=inferred_value,
            inference_basis=inference_basis,
            question_reason=_reason_for(dimension, classification, kind),
        )

    return ConfigFinding(
        dimension=dimension,
        bundle=dimension,
        classification="missing",
        confidence=0.7,
        risk_level=risk_level,
        schema_path=schema_path,
        question_reason=_reason_for(dimension, "missing", kind),
    )


# --- Two-pass detection API ---


def detect_config_findings_pass1(
    kind: str,
    target_id: str,
    sections: dict[str, SectionContent],
    policy_hints: dict[str, Any],
    root: Path,
) -> list[ConfigFinding]:
    """Run only Pass 1 bundles (no cross-bundle dependencies)."""
    canonical_spec = _canonical_spec(kind, target_id, root)
    # Inject target_id into policy_hints so inference helpers can read it
    enriched_hints = dict(policy_hints)
    enriched_hints.setdefault("_target_id", target_id)
    findings: list[ConfigFinding] = []
    for dimension, spec in _BUNDLE_SPECS.items():
        if spec.get("pass_number", 1) != 1:
            continue
        finding = _classify_dimension(dimension, kind, canonical_spec, enriched_hints, sections)
        if finding.classification == "explicit":
            continue
        if dimension == "cadence_monitoring" and kind == "skill" and finding.classification == "missing":
            continue
        findings.append(finding)
    return findings


def merge_pass1_patches(
    spec: dict[str, Any],
    pass1_answers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deep-merge Pass 1 interview answers into a working copy of the spec.

    Each answer in *pass1_answers* is a patch dict (same shape as
    ``_default_patch`` output).  The merged result is used as input for
    Pass 2 bundle detection.
    """
    merged = dict(spec)
    for patch in pass1_answers:
        merged = deep_merge(merged, patch)
    return merged


def detect_config_findings_pass2(
    kind: str,
    target_id: str,
    merged_spec: dict[str, Any],
    sections: dict[str, SectionContent],
    policy_hints: dict[str, Any],
    root: Path,
) -> list[ConfigFinding]:
    """Run only Pass 2 bundles (may read Pass 1 merged output)."""
    # Build enriched hints that include the merged spec data so Pass 2
    # inference functions can read org_hierarchy, coordination, etc.
    enriched_hints = dict(policy_hints)
    enriched_hints.setdefault("_target_id", target_id)
    # Merge the working spec fields into policy_hints so inference
    # helpers can read Pass 1 results (org, operation, policy, governance).
    for key in ("org", "operation", "policy", "governance"):
        if key in merged_spec:
            enriched_hints[key] = deep_merge(enriched_hints.get(key, {}), merged_spec[key])

    findings: list[ConfigFinding] = []
    for dimension, spec in _BUNDLE_SPECS.items():
        if spec.get("pass_number", 1) != 2:
            continue
        finding = _classify_dimension(dimension, kind, merged_spec, enriched_hints, sections)
        if finding.classification == "explicit":
            continue
        if dimension == "cadence_monitoring" and kind == "skill" and finding.classification == "missing":
            continue
        findings.append(finding)
    return findings


def detect_config_findings(
    kind: str,
    target_id: str,
    sections: dict[str, SectionContent],
    policy_hints: dict[str, Any],
    root: Path,
) -> list[ConfigFinding]:
    """Backward-compatible convenience wrapper that runs both passes.

    Pass 1 findings produce default patches that are merged into the
    working spec before Pass 2 runs, so Pass 2 bundles can read Pass 1
    output.
    """
    canonical_spec = _canonical_spec(kind, target_id, root)

    # Pass 1
    pass1_findings = detect_config_findings_pass1(kind, target_id, sections, policy_hints, root)

    # Build default patches from Pass 1 findings for Pass 2 input
    pass1_patches: list[dict[str, Any]] = []
    for finding in pass1_findings:
        patch = _default_patch(finding.bundle, kind, target_id)
        if finding.inferred_value is not None:
            # Use the inferred value instead of blind defaults when available
            bundle_spec = _BUNDLE_SPECS[finding.bundle]
            schema_path = bundle_spec["schema_path"]
            parts = schema_path.split(".")
            nested: dict[str, Any] = finding.inferred_value
            for part in reversed(parts):
                nested = {part: nested}
            patch = deep_merge(patch, nested)
        pass1_patches.append(patch)

    merged_spec = merge_pass1_patches(canonical_spec, pass1_patches)

    # Pass 2
    pass2_findings = detect_config_findings_pass2(kind, target_id, merged_spec, sections, policy_hints, root)

    return pass1_findings + pass2_findings


def _aggregate_risk(findings: list[ConfigFinding]) -> str:
    highest = max(findings, key=lambda item: _RISK_ORDER[item.risk_level])
    return highest.risk_level


def _bundle_provenance(findings: list[ConfigFinding]) -> str:
    if any(finding.classification == "missing" and finding.schema_path for finding in findings):
        return "profile_defaults"
    if any(finding.classification == "inferred" for finding in findings):
        return "target_inference"
    if any(finding.classification == "nonstandard_gap" for finding in findings):
        return "exemplar_comparison"
    return "schema_validity"


def build_decision_bundles(findings: list[ConfigFinding], *, kind: str = "agent", target_id: str = "") -> list[DecisionBundle]:
    grouped: dict[str, list[ConfigFinding]] = {}
    for finding in findings:
        grouped.setdefault(finding.bundle, []).append(finding)

    bundles: list[DecisionBundle] = []
    for bundle_id, items in grouped.items():
        bundle_spec = _BUNDLE_SPECS[bundle_id]
        blocking_level = bundle_spec["blocking_level"]
        if bundle_id == "cadence_monitoring" and any(item.classification == "nonstandard_gap" for item in items):
            blocking_level = "quality"
        bundles.append(
            DecisionBundle(
                bundle_id=bundle_id,
                display_name=bundle_spec["display_name"],
                description=bundle_spec["description"],
                findings=items,
                aggregate_risk=_aggregate_risk(items),
                aggregate_confidence=min(item.confidence for item in items),
                recommendation=_default_recommendation(bundle_id, kind, target_id),
                provenance_basis=_bundle_provenance(items),
                blocking_level=blocking_level,
            )
        )
    order = {"blocking": 0, "stabilizing": 1, "quality": 2}
    bundles.sort(key=lambda item: (order[item.blocking_level], item.bundle_id))
    return bundles


def recommendation_patch(bundle: DecisionBundle, *, kind: str, target_id: str) -> dict[str, Any]:
    return _default_patch(bundle.bundle_id, kind, target_id)
