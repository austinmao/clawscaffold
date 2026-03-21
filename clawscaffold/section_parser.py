"""Runtime section parsing and lightweight policy inference."""

from __future__ import annotations

import re
from typing import Any

from clawscaffold.constants import (
    CANONICAL_SKILL_SECTION_IDS,
    CANONICAL_SOUL_SECTION_IDS,
    CANONICAL_SOUL_SECTION_ORDER,
    SOUL_SECTION_IDS,
    STANDARD_SKILL_SECTION_IDS,
)
from clawscaffold.models import SectionContent
from clawscaffold.utils import load_frontmatter, sha256_prefix, strip_managed_markers

_SKILL_REF_PATTERN = re.compile(r"`?(skills/[a-z0-9/_-]+)`?")
_MEMORY_PATH_PATTERN = re.compile(r"`?(memory/[A-Za-z0-9._/-]+)`?")
_CHANNEL_PATTERN = re.compile(r"\b(imessage|telegram|slack|discord|whatsapp|email|sms)\b", re.IGNORECASE)
_REASONING_PATTERN = re.compile(r"reasoning_effort:\s*(low|medium|high|xhigh)", re.IGNORECASE)


def _slugify_heading(heading: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", heading.lower())).strip("_") or "section"


def _unique_section_id(section_id: str, seen: dict[str, int]) -> str:
    count = seen.get(section_id, 0)
    seen[section_id] = count + 1
    if count == 0:
        return section_id
    return f"{section_id}_{count + 1}"


def _split_by_heading(text: str, pattern: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    if not matches:
        return []
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip("\n")
        sections.append((heading, body))
    return sections


def parse_sections(text: str) -> list[SectionContent]:
    """Parse SOUL.md style `#` headings into ordered section records."""

    sections: list[SectionContent] = []
    seen: dict[str, int] = {}
    for order, (heading, body) in enumerate(_split_by_heading(text, r"^#\s+(.+?)\s*$")):
        content = strip_managed_markers(body)
        base_id = SOUL_SECTION_IDS.get(heading, _slugify_heading(heading))
        section_id = _unique_section_id(base_id, seen)
        sections.append(
            SectionContent(
                id=section_id,
                heading=heading,
                content=content,
                source="imported",
                custom=heading not in SOUL_SECTION_IDS,
                content_hash=sha256_prefix(content),
                order=order,
            )
        )
    return sections


def parse_skill_sections(text: str) -> tuple[dict[str, Any], list[SectionContent]]:
    """Parse SKILL.md frontmatter and body sections."""

    frontmatter, body = load_frontmatter(text)
    sections: list[SectionContent] = []
    seen: dict[str, int] = {}

    preamble, divider, remainder = body.partition("\n## ")
    preamble = preamble.strip("\n")
    if preamble:
        preamble_heading_match = re.match(r"^#\s+(.+?)\s*$", preamble, re.MULTILINE)
        if preamble_heading_match:
            heading = preamble_heading_match.group(1).strip()
            heading_line = f"# {heading}"
            content = preamble.replace(heading_line, "", 1).strip("\n")
        else:
            heading = "Overview"
            content = preamble
        content = strip_managed_markers(content)
        section_id = _unique_section_id(STANDARD_SKILL_SECTION_IDS.get(heading.lower(), _slugify_heading(heading)), seen)
        sections.append(
            SectionContent(
                id=section_id,
                heading=heading,
                content=content,
                source="imported",
                custom=heading.lower() not in STANDARD_SKILL_SECTION_IDS,
                content_hash=sha256_prefix(content),
                order=len(sections),
            )
        )

    body_for_split = f"## {remainder}" if divider else ""
    for heading, content in _split_by_heading(body_for_split, r"^##\s+(.+?)\s*$"):
        content = strip_managed_markers(content)
        key = STANDARD_SKILL_SECTION_IDS.get(heading.lower(), _slugify_heading(heading))
        section_id = _unique_section_id(key, seen)
        sections.append(
            SectionContent(
                id=section_id,
                heading=heading,
                content=content,
                source="imported",
                custom=heading.lower() not in STANDARD_SKILL_SECTION_IDS,
                content_hash=sha256_prefix(content),
                order=len(sections),
            )
        )

    if not sections and body.strip():
        content = strip_managed_markers(body.strip("\n"))
        sections.append(
            SectionContent(
                id="usage",
                heading="Usage",
                content=content,
                source="imported",
                custom=False,
                content_hash=sha256_prefix(content),
                order=0,
            )
        )

    return frontmatter, sections


# ---------------------------------------------------------------------------
# Section migration: classify existing prose into canonical 10-section template
# ---------------------------------------------------------------------------

_HEADING_ALIASES: dict[str, str] = {
    "who i am": "who_i_am",
    "identity": "who_i_am",
    "role": "who_i_am",
    "core principles": "core_principles",
    "principles": "core_principles",
    "values": "core_principles",
    "guidelines": "core_principles",
    "boundaries": "boundaries",
    "limitations": "boundaries",
    "what i will not do": "boundaries",
    "scope limits": "scope_limits",
    "scope": "scope_limits",
    "authorized actions": "scope_limits",
    "communication style": "communication_style",
    "tone": "communication_style",
    "voice": "communication_style",
    "response format": "communication_style",
    "channels": "channels",
    "channel bindings": "channels",
    "escalation": "escalation",
    "escalation chain": "escalation",
    "handoff": "escalation",
    "security rules": "security_rules",
    "security": "security_rules",
    "prompt injection": "security_rules",
    "session initialization": "session_initialization",
    "session init": "session_initialization",
    "startup": "session_initialization",
    "on session start": "session_initialization",
    "memory": "memory",
    "memory management": "memory",
    "persistence": "memory",
}


def migrate_sections(
    existing_sections: list[SectionContent],
) -> dict[str, SectionContent]:
    """Classify existing SOUL.md sections into the 10-section canonical template.

    Returns a dict mapping canonical section_id -> SectionContent with
    source set to ``"migrated"``.  Unmatched sections are kept with custom=True.
    """
    canonical_order = {sid: idx for idx, (sid, _) in enumerate(CANONICAL_SOUL_SECTION_ORDER)}
    result: dict[str, SectionContent] = {}
    unmatched: list[SectionContent] = []

    for section in existing_sections:
        heading_lower = section.heading.lower().strip()
        canonical_id = CANONICAL_SOUL_SECTION_IDS.get(section.heading)
        if canonical_id is None:
            canonical_id = _HEADING_ALIASES.get(heading_lower)

        if canonical_id is not None:
            migrated = SectionContent(
                id=canonical_id,
                heading=section.heading,
                content=section.content,
                source="migrated",
                custom=False,
                content_hash=section.content_hash,
                order=canonical_order.get(canonical_id, 99),
            )
            if canonical_id in result:
                existing = result[canonical_id]
                merged_content = existing.content + "\n\n" + migrated.content
                result[canonical_id] = SectionContent(
                    id=canonical_id,
                    heading=existing.heading,
                    content=merged_content,
                    source="migrated",
                    custom=False,
                    content_hash=sha256_prefix(merged_content),
                    order=existing.order,
                )
            else:
                result[canonical_id] = migrated
        else:
            unmatched.append(section)

    base_order = len(CANONICAL_SOUL_SECTION_ORDER)
    for idx, section in enumerate(unmatched):
        slug = _slugify_heading(section.heading)
        result[slug] = SectionContent(
            id=slug,
            heading=section.heading,
            content=section.content,
            source="migrated",
            custom=True,
            content_hash=section.content_hash,
            order=base_order + idx,
        )

    return result


def migrate_skill_sections(
    existing_sections: list[SectionContent],
) -> dict[str, SectionContent]:
    """Classify existing SKILL.md sections into canonical skill template."""
    _skill_aliases: dict[str, str] = {
        "overview": "purpose",
        "description": "purpose",
        "about": "purpose",
        "usage": "instructions",
        "how to use": "instructions",
        "steps": "instructions",
        "parameters": "inputs",
        "input": "inputs",
        "inputs": "inputs",
        "arguments": "inputs",
        "output": "outputs",
        "outputs": "outputs",
        "returns": "outputs",
        "results": "outputs",
        "error handling": "error_handling",
        "errors": "error_handling",
        "troubleshooting": "error_handling",
    }

    result: dict[str, SectionContent] = {}
    unmatched: list[SectionContent] = []

    for section in existing_sections:
        heading_lower = section.heading.lower().strip()
        canonical_id = _skill_aliases.get(heading_lower)
        if canonical_id is None:
            canonical_id = CANONICAL_SKILL_SECTION_IDS.get(heading_lower)

        if canonical_id is not None:
            result[canonical_id] = SectionContent(
                id=canonical_id,
                heading=section.heading,
                content=section.content,
                source="migrated",
                custom=False,
                content_hash=section.content_hash,
                order=section.order,
            )
        else:
            unmatched.append(section)

    for idx, section in enumerate(unmatched):
        slug = _slugify_heading(section.heading)
        result[slug] = SectionContent(
            id=slug,
            heading=section.heading,
            content=section.content,
            source="migrated",
            custom=True,
            content_hash=section.content_hash,
            order=100 + idx,
        )

    return result


def infer_policy_hints(sections: list[SectionContent]) -> dict[str, Any]:
    """Infer policy settings and references from section text."""

    combined = "\n".join(section.content for section in sections)
    hints: dict[str, Any] = {"skills": [], "memory_paths": [], "approvals": [], "channels": []}

    lower = combined.lower()
    if "enhanced retrieval tier" in lower:
        hints.setdefault("memory", {})["retrieval_mode"] = "enhanced_tier"
    elif "no memory" in lower:
        hints.setdefault("memory", {})["retrieval_mode"] = "none"
    else:
        hints.setdefault("memory", {})["retrieval_mode"] = "universal_file"

    reasoning_match = _REASONING_PATTERN.search(combined)
    if reasoning_match:
        effort = reasoning_match.group(1).lower()
        complexity = "medium"
        if effort in {"low"}:
            complexity = "low"
        elif effort in {"high", "xhigh"}:
            complexity = "high"
        hints.setdefault("cognition", {})["complexity"] = complexity
        hints.setdefault("cognition", {})["reasoning_effort"] = effort

    skills = sorted({match.group(1) for match in _SKILL_REF_PATTERN.finditer(combined)})
    if skills:
        hints["skills"] = skills

    memory_paths = sorted({match.group(1) for match in _MEMORY_PATH_PATTERN.finditer(combined)})
    if memory_paths:
        hints["memory_paths"] = memory_paths

    channels = sorted({match.group(1).lower() for match in _CHANNEL_PATTERN.finditer(combined)})
    if channels:
        hints["channels"] = channels

    approvals: list[str] = []
    if re.search(r"\b(approval|approve|confirm|explicit approval)\b", combined, re.IGNORECASE):
        approvals.append("confirm")
    if approvals:
        hints["approvals"] = approvals

    return hints
