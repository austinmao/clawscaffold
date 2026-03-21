"""Three-level conflict detection for scaffold adopt.

Level 1: Intra-file — opposing polarity rules within a single SOUL.md/SKILL.md
Level 2: Agent-skill cross-reference — agent rules vs skill instructions
Level 3: Agent-config — migrated prose vs assembled config values

Unresolved conflicts block apply.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Conflict:
    """A detected conflict between two sources."""

    level: int  # 1, 2, or 3
    severity: str  # critical, major, minor
    source_a: dict[str, Any]  # {file, section, line, content}
    source_b: dict[str, Any]
    description: str
    recommendation: str
    resolved: bool = False
    resolution: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Patterns that express polarity.  Each tuple: (compiled regex, polarity)
_RULE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bmust\s+not\s+(\w+)", re.IGNORECASE), "negative"),
    (re.compile(r"\bnever\s+(\w+)", re.IGNORECASE), "negative"),
    (re.compile(r"\balways\s+(\w+)", re.IGNORECASE), "positive"),
    (re.compile(r"\bmust\s+(\w+)", re.IGNORECASE), "positive"),
]


@dataclass
class _Rule:
    """An extracted declarative rule."""

    verb: str  # the captured word following the polarity keyword
    polarity: str  # "positive" or "negative"
    keyword: str  # the full match text (e.g. "never send")
    section: str  # section id / key where found
    content: str  # the full line or surrounding text


def _extract_rules(sections: dict[str, Any]) -> list[_Rule]:
    """Pull declarative rules from every section's content."""
    rules: list[_Rule] = []
    for section_key, section_val in sections.items():
        # Accept both raw string content and objects with a .content attr / dict
        text = _section_text(section_val)
        if not text:
            continue
        for line in text.splitlines():
            for pattern, polarity in _RULE_PATTERNS:
                for match in pattern.finditer(line):
                    verb = match.group(1).lower()
                    # Guard: "must not X" would also match "must X" — skip
                    # the positive "must" hit when the actual text is "must not".
                    if polarity == "positive" and pattern.pattern.startswith(r"\bmust\s+"):
                        preceding = line[: match.start() + len("must")]
                        if re.search(r"\bmust\s+not\b", preceding, re.IGNORECASE):
                            continue
                    rules.append(
                        _Rule(
                            verb=verb,
                            polarity=polarity,
                            keyword=match.group(0),
                            section=section_key,
                            content=line.strip(),
                        )
                    )
    return rules


def _section_text(section_val: Any) -> str:
    """Extract combined text from a section value.

    Handles:
    - plain str
    - dict with 'content' key
    - object with .content attribute
    - list of any of the above
    """
    if isinstance(section_val, str):
        return section_val
    if isinstance(section_val, dict):
        return str(section_val.get("content", ""))
    if isinstance(section_val, list):
        return "\n".join(_section_text(item) for item in section_val)
    if hasattr(section_val, "content"):
        return str(section_val.content)
    return str(section_val)


def _combined_text(sections: dict[str, Any]) -> str:
    """Join all section content into a single string for prose searches."""
    parts: list[str] = []
    for val in sections.values():
        t = _section_text(val)
        if t:
            parts.append(t)
    return "\n".join(parts)


def _get_nested(data: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Retrieve a value from a nested dict using dot-separated keys."""
    keys = dotted_key.split(".")
    current: Any = data
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return default
        if current is None:
            return default
    return current


# ---------------------------------------------------------------------------
# Level 1 — Intra-file conflicts
# ---------------------------------------------------------------------------

def detect_intra_file_conflicts(
    sections: dict[str, Any],
    deep_check: bool = False,
) -> list[Conflict]:
    """Level 1: Find opposing-polarity rules within a single file."""
    rules = _extract_rules(sections)
    conflicts: list[Conflict] = []
    seen_pairs: set[tuple[int, int]] = set()

    for i, rule_a in enumerate(rules):
        for j, rule_b in enumerate(rules):
            if j <= i:
                continue
            pair_key = (i, j)
            if pair_key in seen_pairs:
                continue

            # Same verb, opposing polarity → conflict
            if rule_a.verb == rule_b.verb and rule_a.polarity != rule_b.polarity:
                seen_pairs.add(pair_key)

                # Direct same-section contradictions are major;
                # cross-section with same verb are also major.
                severity = "major"

                desc = (
                    f"Opposing rules for verb '{rule_a.verb}': "
                    f"'{rule_a.keyword}' ({rule_a.polarity}) vs "
                    f"'{rule_b.keyword}' ({rule_b.polarity})"
                )
                if deep_check:
                    desc += " [deep_check=True: semantic analysis deferred to future LLM pass]"

                conflicts.append(
                    Conflict(
                        level=1,
                        severity=severity,
                        source_a={
                            "section": rule_a.section,
                            "content": rule_a.content,
                        },
                        source_b={
                            "section": rule_b.section,
                            "content": rule_b.content,
                        },
                        description=desc,
                        recommendation=(
                            f"Resolve which directive for '{rule_a.verb}' should take precedence "
                            f"and remove or qualify the other."
                        ),
                    )
                )

    return conflicts


# ---------------------------------------------------------------------------
# Level 2 — Agent-skill cross-reference
# ---------------------------------------------------------------------------

def detect_agent_skill_conflicts(
    agent_sections: dict[str, Any],
    skill_sections_list: list[dict[str, Any]],
    deep_check: bool = False,
) -> list[Conflict]:
    """Level 2: Cross-reference agent SOUL.md rules with skill instructions."""
    conflicts: list[Conflict] = []
    agent_rules = _extract_rules(agent_sections)

    # Collect the negative rules from the agent (things the agent must never do).
    negative_rules = [r for r in agent_rules if r.polarity == "negative"]

    for skill_idx, skill_sections in enumerate(skill_sections_list):
        skill_label = f"skill[{skill_idx}]"
        skill_text = _combined_text(skill_sections).lower()

        # Check 1: agent "never {verb}" but skill text contains the verb
        for neg_rule in negative_rules:
            verb = neg_rule.verb
            # Look for the verb in skill text as a standalone word
            if re.search(rf"\b{re.escape(verb)}\b", skill_text):
                desc = (
                    f"Agent prohibits '{neg_rule.keyword}' but {skill_label} "
                    f"references '{verb}'"
                )
                if deep_check:
                    desc += " [deep_check=True: semantic analysis deferred to future LLM pass]"

                conflicts.append(
                    Conflict(
                        level=2,
                        severity="critical",
                        source_a={
                            "source": "agent",
                            "section": neg_rule.section,
                            "content": neg_rule.content,
                        },
                        source_b={
                            "source": skill_label,
                            "content": _find_context_line(skill_sections, verb),
                        },
                        description=desc,
                        recommendation=(
                            f"Either relax the agent prohibition on '{verb}' "
                            f"or remove the action from the skill."
                        ),
                    )
                )

        # Check 2: agent declares channel bindings but skill doesn't reference channel
        agent_text = _combined_text(agent_sections).lower()
        channel_types = ["imessage", "telegram", "slack", "whatsapp", "email", "sms"]
        for channel in channel_types:
            # Agent mentions the channel in a binding-like context
            if re.search(
                rf"\b(channel|binding|bound\s+to|communicate\s+via)\b.*\b{channel}\b",
                agent_text,
            ):
                # Check all skills collectively for this channel mention
                any_skill_has_channel = False
                for s_sections in skill_sections_list:
                    if channel in _combined_text(s_sections).lower():
                        any_skill_has_channel = True
                        break
                if not any_skill_has_channel and skill_sections_list:
                    conflicts.append(
                        Conflict(
                            level=2,
                            severity="major",
                            source_a={
                                "source": "agent",
                                "content": f"Agent declares channel binding for '{channel}'",
                            },
                            source_b={
                                "source": "skills",
                                "content": f"No skill references channel '{channel}'",
                            },
                            description=(
                                f"Agent declares '{channel}' channel binding "
                                f"but no skill references that channel"
                            ),
                            recommendation=(
                                f"Add a skill that handles '{channel}' or "
                                f"remove the channel binding from the agent."
                            ),
                        )
                    )

    return conflicts


def _find_context_line(sections: dict[str, Any], verb: str) -> str:
    """Find the first line in sections that mentions *verb* for context."""
    for val in sections.values():
        text = _section_text(val)
        for line in text.splitlines():
            if re.search(rf"\b{re.escape(verb)}\b", line, re.IGNORECASE):
                return line.strip()
    return f"(contains reference to '{verb}')"


# ---------------------------------------------------------------------------
# Level 3 — Agent-config mismatch
# ---------------------------------------------------------------------------

def detect_config_prose_conflicts(
    spec: dict[str, Any],
    migrated_sections: dict[str, Any],
) -> list[Conflict]:
    """Level 3: Cross-reference assembled config with migrated prose."""
    conflicts: list[Conflict] = []
    prose = _combined_text(migrated_sections).lower()

    # Check 1: prose mentions "high reasoning" but spec has low complexity
    complexity = _get_nested(spec, "policy.cognition.complexity")
    if complexity is not None:
        complexity_str = str(complexity).lower()
        if "high reasoning" in prose and complexity_str == "low":
            conflicts.append(
                Conflict(
                    level=3,
                    severity="major",
                    source_a={
                        "source": "spec",
                        "path": "policy.cognition.complexity",
                        "value": complexity_str,
                    },
                    source_b={
                        "source": "prose",
                        "content": "Prose references 'high reasoning'",
                    },
                    description=(
                        "Prose mentions 'high reasoning' but spec sets "
                        f"policy.cognition.complexity to '{complexity_str}'"
                    ),
                    recommendation=(
                        "Set policy.cognition.complexity to 'high' or "
                        "update prose to remove the 'high reasoning' claim."
                    ),
                )
            )

    # Check 2: prose mentions escalating to agent X but escalation chain lacks X
    escalation_chain = _get_nested(spec, "operation.escalation.chain") or []
    # Find all "escalate to <agent>" / "hand off to <agent>" patterns
    escalation_mentions = re.findall(
        r"(?:escalat(?:e|ing)\s+to|hand\s*(?:off|over)\s+to)\s+([a-z0-9_-]+)",
        prose,
    )
    for agent_ref in escalation_mentions:
        if agent_ref not in escalation_chain:
            conflicts.append(
                Conflict(
                    level=3,
                    severity="major",
                    source_a={
                        "source": "spec",
                        "path": "operation.escalation.chain",
                        "value": escalation_chain,
                    },
                    source_b={
                        "source": "prose",
                        "content": f"Prose mentions escalating to '{agent_ref}'",
                    },
                    description=(
                        f"Prose mentions escalating to '{agent_ref}' but "
                        f"operation.escalation.chain does not include it"
                    ),
                    recommendation=(
                        f"Add '{agent_ref}' to operation.escalation.chain or "
                        f"remove the escalation reference from prose."
                    ),
                )
            )

    # Check 3: prose mentions specific channels but operation.channels lacks them
    configured_channels = _get_nested(spec, "operation.channels") or []
    # Normalize to lowercase list
    configured_channels_lower = [str(c).lower() for c in configured_channels]
    channel_keywords = ["imessage", "telegram", "slack", "whatsapp", "email", "sms"]
    for channel in channel_keywords:
        if re.search(rf"\b{channel}\b", prose) and channel not in configured_channels_lower:
            conflicts.append(
                Conflict(
                    level=3,
                    severity="major",
                    source_a={
                        "source": "spec",
                        "path": "operation.channels",
                        "value": configured_channels,
                    },
                    source_b={
                        "source": "prose",
                        "content": f"Prose mentions '{channel}' channel",
                    },
                    description=(
                        f"Prose references '{channel}' channel but "
                        f"operation.channels does not include it"
                    ),
                    recommendation=(
                        f"Add '{channel}' to operation.channels or "
                        f"remove the channel reference from prose."
                    ),
                )
            )

    # Check 4: prose says "never send" but side_effects includes send_message
    side_effects = _get_nested(spec, "operation.side_effects") or []
    side_effects_lower = [str(s).lower() for s in side_effects]
    if re.search(r"\bnever\s+send\b", prose) and "send_message" in side_effects_lower:
        conflicts.append(
            Conflict(
                level=3,
                severity="major",
                source_a={
                    "source": "spec",
                    "path": "operation.side_effects",
                    "value": side_effects,
                },
                source_b={
                    "source": "prose",
                    "content": "Prose states 'never send'",
                },
                description=(
                    "Prose says 'never send' but operation.side_effects "
                    "includes 'send_message'"
                ),
                recommendation=(
                    "Remove 'send_message' from operation.side_effects or "
                    "update prose to allow sending."
                ),
            )
        )

    return conflicts


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

_LEVEL_NAMES = {1: "intra", 2: "cross", 3: "config"}


def write_conflict_report(
    conflicts: list[Conflict],
    run_dir: Path,
    level: int,
) -> Path:
    """Write conflict report YAML to {run_dir}/conflicts-{level_name}.yaml."""
    level_name = _LEVEL_NAMES.get(level, f"level{level}")
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / f"conflicts-{level_name}.yaml"

    payload = [asdict(c) for c in conflicts]
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)

    return out_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def has_unresolved_conflicts(conflicts: list[Conflict]) -> bool:
    """Return True if any conflict has resolved=False."""
    return any(not c.resolved for c in conflicts)
