"""Extract condensed agent identity from SOUL.md for payloadTemplate injection."""

from __future__ import annotations

import re
from pathlib import Path

# Sections that define agent identity (extracted for payloadTemplate.text)
_IDENTITY_SECTIONS = {
    "who i am",
    "core principles",
    "boundaries",
    "routing rules",
    "communication style",
    "scope limits",
}

# Sections explicitly excluded (operational, not identity)
_EXCLUDED_SECTIONS = {
    "security rules",
    "memory",
    "tools",
    "heartbeat",
}

MAX_WORDS = 300


def _parse_sections(content: str) -> dict[str, str]:
    """Parse markdown into {heading_lower: body} dict."""
    sections: dict[str, str] = {}
    current_heading = ""
    current_lines: list[str] = []

    for line in content.splitlines():
        heading_match = re.match(r"^#{1,3}\s+(.+)$", line)
        if heading_match:
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = heading_match.group(1).strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


def _truncate_to_words(text: str, max_words: int) -> str:
    """Truncate text to max_words, preserving complete sentences."""
    words = text.split()
    if len(words) <= max_words:
        return text

    truncated = " ".join(words[:max_words])
    # Try to end at a sentence boundary
    last_period = truncated.rfind(".")
    if last_period > len(truncated) // 2:
        return truncated[: last_period + 1]
    return truncated + "..."


def condense_soul(soul_content: str, max_words: int = MAX_WORDS) -> str:
    """Extract condensed identity from SOUL.md content.

    Pulls identity-defining sections (Who I Am, Core Principles,
    Boundaries, Routing Rules) and truncates to ~200 words.

    Args:
        soul_content: Raw SOUL.md text.
        max_words: Maximum word count for output.

    Returns:
        Condensed identity string suitable for payloadTemplate.text.
        Empty string if no identity sections found.
    """
    sections = _parse_sections(soul_content)

    identity_parts: list[str] = []
    for heading, body in sections.items():
        heading_lower = heading.lower()
        if heading_lower in _EXCLUDED_SECTIONS:
            continue
        if heading_lower in _IDENTITY_SECTIONS:
            identity_parts.append(body)

    if not identity_parts:
        # Fallback: use the first non-empty section
        for heading, body in sections.items():
            if body and heading.lower() not in _EXCLUDED_SECTIONS:
                identity_parts.append(body)
                break

    if not identity_parts:
        return ""

    combined = "\n\n".join(identity_parts)
    # Strip markdown formatting for cleaner injection
    combined = re.sub(r"\*\*(.+?)\*\*", r"\1", combined)  # bold
    combined = re.sub(r"\*(.+?)\*", r"\1", combined)  # italic
    combined = re.sub(r"^\s*[-*]\s+", "- ", combined, flags=re.MULTILINE)  # normalize bullets
    combined = re.sub(r"\n{3,}", "\n\n", combined)  # collapse blank lines

    return _truncate_to_words(combined, max_words)


def condense_soul_file(
    soul_path: Path,
    max_words: int = MAX_WORDS,
) -> str:
    """Read SOUL.md file and return condensed identity.

    Args:
        soul_path: Path to SOUL.md file.
        max_words: Maximum word count.

    Returns:
        Condensed identity string. Empty string if file missing.
    """
    if not soul_path.is_file():
        return ""
    return condense_soul(soul_path.read_text(), max_words=max_words)
