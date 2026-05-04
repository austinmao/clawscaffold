"""CONFIG.md generator for agent self-awareness.

Produces a human-readable workspace file from a canonical spec.
Never includes concrete model names — uses registry key only.
Auto-appended to agent.workspace_files during apply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _get(data: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
    """Safe nested dict access via dot-separated path."""
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(part)
        if current is None:
            return default
    return current


def _fmt_number(value: int | float | None) -> str:
    """Format a number with commas (e.g. 50000 -> '50,000')."""
    if value is None:
        return "0"
    return f"{int(value):,}"


def _yes_no(value: bool | None) -> str:
    return "yes" if value else "no"


def _comma_list(items: list[str] | None) -> str:
    if not items:
        return "none"
    return ", ".join(items)


def _format_channel(channel: dict[str, Any]) -> str:
    """Format a single channel entry for the Channels section."""
    ch_type = channel.get("type", "unknown")
    parts: list[str] = []

    audience = channel.get("audience")
    if audience:
        parts.append(audience)

    mode = channel.get("mode")
    if mode:
        parts.append(mode)

    approval = channel.get("approval_posture")
    if approval:
        parts.append(approval)

    detail = ", ".join(parts) if parts else "configured"
    return f"- **{ch_type}**: {detail}"


def _build_identity_section(spec: dict[str, Any]) -> list[str]:
    agent_id = spec.get("id", "unknown")
    org = spec.get("org", {})
    org_level = org.get("org_level", "ic")
    department = org.get("department", "unknown")
    reports_to = org.get("reports_to") or "none"
    manages = _comma_list(org.get("manages"))

    return [
        "## Identity",
        f"- **ID**: {agent_id}",
        f"- **Org level**: {org_level}",
        f"- **Department**: {department}",
        f"- **Reports to**: {reports_to}",
        f"- **Manages**: {manages}",
    ]


def _build_cognition_section(spec: dict[str, Any]) -> list[str]:
    cognition = _get(spec, "policy.cognition", {})
    complexity = cognition.get("complexity", "medium")
    cost_posture = cognition.get("cost_posture", "standard")
    risk_posture = cognition.get("risk_posture", "low")
    registry_key = f"{complexity}/{cost_posture}/{risk_posture}"

    return [
        "## Cognition",
        f"- **Complexity**: {complexity}",
        f"- **Cost posture**: {cost_posture}",
        f"- **Risk posture**: {risk_posture}",
        f"- **Registry key**: {registry_key}",
    ]


def _build_coordination_section(spec: dict[str, Any]) -> list[str] | None:
    coordination = _get(spec, "operation.coordination", {})
    if not coordination:
        return None

    pattern = coordination.get("pattern", "standalone")
    can_spawn = coordination.get("can_spawn", False)
    max_spawn_depth = coordination.get("max_spawn_depth", 0)
    produces_for = _comma_list(coordination.get("produces_handoffs_for"))

    return [
        "## Coordination",
        f"- **Pattern**: {pattern}",
        f"- **Can spawn**: {_yes_no(can_spawn)} (max depth: {max_spawn_depth})",
        f"- **Produces handoffs for**: {produces_for}",
    ]


def _build_escalation_section(spec: dict[str, Any]) -> list[str] | None:
    escalation = _get(spec, "operation.escalation", {})
    if not escalation:
        return None

    chain = escalation.get("chain", ["operator"])
    timeout = escalation.get("timeout_seconds", 300)
    arrow = " \u2192 "
    chain_str = arrow.join(chain)

    return [
        "## Escalation",
        f"- **Chain**: {chain_str}",
        f"- **Timeout**: {timeout}s",
    ]


def _build_channels_section(spec: dict[str, Any]) -> list[str] | None:
    channels = _get(spec, "operation.channels", [])
    if not channels:
        return None

    lines = ["## Channels"]
    for ch in channels:
        lines.append(_format_channel(ch))
    return lines


def _build_resource_limits_section(spec: dict[str, Any]) -> list[str] | None:
    limits = _get(spec, "policy.resource_limits", {})
    if not limits:
        return None

    tokens = limits.get("max_tokens_per_session", 50000)
    sessions = limits.get("max_sessions_per_day", 100)
    outbound = limits.get("max_outbound_per_day", 50)

    return [
        "## Resource Limits",
        f"- **Tokens/session**: {_fmt_number(tokens)}",
        f"- **Sessions/day**: {_fmt_number(sessions)}",
        f"- **Outbound/day**: {_fmt_number(outbound)}",
    ]


def _build_scheduling_section(spec: dict[str, Any]) -> list[str] | None:
    scheduling = _get(spec, "operation.scheduling", {})
    if not scheduling:
        return None

    quiet_hours = scheduling.get("quiet_hours")
    if quiet_hours and isinstance(quiet_hours, dict):
        start = quiet_hours.get("start", "")
        end = quiet_hours.get("end", "")
        tz = quiet_hours.get("timezone", "")
        quiet_str = f"{start}-{end} {tz}".strip()
    else:
        quiet_str = "none"

    max_concurrent = scheduling.get("max_concurrent", 1)
    sla = scheduling.get("sla_response_seconds", 3600)

    return [
        "## Scheduling",
        f"- **Quiet hours**: {quiet_str}",
        f"- **Max concurrent**: {max_concurrent}",
        f"- **SLA**: {sla}s response",
    ]


def _build_compliance_section(spec: dict[str, Any]) -> list[str] | None:
    compliance = _get(spec, "policy.compliance", {})
    if not compliance:
        return None

    classification = compliance.get("data_classification", "internal")
    handles_pii = compliance.get("handles_pii", False)
    retention = compliance.get("retention_days", 90)

    return [
        "## Compliance",
        f"- **Data classification**: {classification}",
        f"- **Handles PII**: {_yes_no(handles_pii)}",
        f"- **Retention**: {retention} days",
    ]


def _build_observability_section(spec: dict[str, Any]) -> list[str] | None:
    observability = _get(spec, "policy.observability", {})
    if not observability:
        return None

    log_level = observability.get("log_level", "standard")
    cost_tracking = observability.get("cost_tracking", True)

    return [
        "## Observability",
        f"- **Log level**: {log_level}",
        f"- **Cost tracking**: {_yes_no(cost_tracking)}",
    ]


def generate_config_md(spec: dict[str, Any]) -> str:
    """Generate CONFIG.md content from a canonical spec.

    Returns markdown string with resolved config sections.
    No concrete model names — registry key only.
    """
    agent_id = spec.get("id", "unknown")
    kind = spec.get("kind", "agent")

    # Determine catalog path for the header comment
    kind_plural = f"{kind}s"
    header = f"<!-- oc:generated from catalog/{kind_plural}/{agent_id}.yaml \u2014 do not edit manually -->"

    sections: list[list[str]] = []

    # Identity is always present
    sections.append(_build_identity_section(spec))

    # Cognition is always present
    sections.append(_build_cognition_section(spec))

    # Optional sections — skip if entirely default/empty
    for builder in (
        _build_coordination_section,
        _build_escalation_section,
        _build_channels_section,
        _build_resource_limits_section,
        _build_scheduling_section,
        _build_compliance_section,
        _build_observability_section,
    ):
        result = builder(spec)
        if result is not None:
            sections.append(result)

    lines = [header, "# Agent Configuration", ""]
    for i, section_lines in enumerate(sections):
        lines.extend(section_lines)
        if i < len(sections) - 1:
            lines.append("")

    return "\n".join(lines) + "\n"


def write_config_md(spec: dict[str, Any], target_dir: Path) -> Path:
    """Write CONFIG.md to the agent's workspace directory.

    Returns the written file path.
    """
    content = generate_config_md(spec)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "CONFIG.md"
    path.write_text(content, encoding="utf-8")
    return path
