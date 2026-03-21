"""Content preservation helpers for scaffold apply."""

from __future__ import annotations

import re
from pathlib import Path

from clawscaffold.models import ContentLossReport, FileWriteEntry
from clawscaffold.utils import now_iso, upsert_marked_section

_MARKED_SECTION_RE = re.compile(r'<!-- oc:section id="([^"]+)"[^>]*-->.*?<!-- /oc:section id="\1" -->', re.DOTALL)
_MERGEABLE_HYBRID_FILES = {"AGENTS.md", "TOOLS.md", "HEARTBEAT.md"}


def _normalize_text(text: str) -> set[str]:
    lines: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            continue
        lines.add(line)
    return lines


def _normalize_lines(path: Path) -> set[str]:
    return _normalize_text(path.read_text(encoding="utf-8"))


def _extract_marked_sections(document: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(0)) for match in _MARKED_SECTION_RE.finditer(document)]


def preview_runtime_content(entry: FileWriteEntry, runtime_path: Path | None = None) -> str:
    """Return the exact content that would be written for this entry."""

    live_path = runtime_path or Path(entry.runtime_path)
    if entry.ownership_class != "hybrid" or live_path.name not in _MERGEABLE_HYBRID_FILES or not live_path.exists():
        return entry.content

    sections = _extract_marked_sections(entry.content)
    if not sections:
        return entry.content

    merged = live_path.read_text(encoding="utf-8")
    for marker_id, block in sections:
        merged = upsert_marked_section(merged, marker_id, block)
    return merged


def should_enforce_content_loss(entry: FileWriteEntry) -> bool:
    return entry.ownership_class != "generated"


def compute_content_loss(live_path: Path, rendered_path: Path) -> ContentLossReport:
    """Compare rendered output to the live runtime file."""

    if not live_path.exists():
        return ContentLossReport(
            target_id=live_path.parent.name,
            target_kind="skill" if live_path.name == "SKILL.md" else "agent",
            live_path=str(live_path),
            rendered_path=str(rendered_path),
            live_line_count=0,
            preserved_line_count=0,
            preservation_pct=100.0,
            lines_lost=[],
            lines_added=[],
            passed=True,
            computed_at=now_iso(),
        )

    live_lines = _normalize_lines(live_path)
    rendered_lines = _normalize_lines(rendered_path)
    preserved = live_lines & rendered_lines
    live_count = len(live_lines)
    preserved_count = len(preserved)
    pct = 100.0 if live_count == 0 else round((preserved_count / live_count) * 100, 2)

    return ContentLossReport(
        target_id=live_path.parent.name,
        target_kind="skill" if live_path.name == "SKILL.md" else "agent",
        live_path=str(live_path),
        rendered_path=str(rendered_path),
        live_line_count=live_count,
        preserved_line_count=preserved_count,
        preservation_pct=pct,
        lines_lost=sorted(live_lines - rendered_lines),
        lines_added=sorted(rendered_lines - live_lines),
        passed=pct >= 90.0,
        computed_at=now_iso(),
    )


def compute_content_loss_preview(
    live_path: Path,
    rendered_content: str,
    rendered_path: Path | None = None,
) -> ContentLossReport:
    """Compare rendered preview content to the live runtime file."""

    if not live_path.exists():
        return ContentLossReport(
            target_id=live_path.parent.name,
            target_kind="skill" if live_path.name == "SKILL.md" else "agent",
            live_path=str(live_path),
            rendered_path=str(rendered_path or "<preview>"),
            live_line_count=0,
            preserved_line_count=0,
            preservation_pct=100.0,
            lines_lost=[],
            lines_added=[],
            passed=True,
            computed_at=now_iso(),
        )

    live_lines = _normalize_lines(live_path)
    rendered_lines = _normalize_text(rendered_content)
    preserved = live_lines & rendered_lines
    live_count = len(live_lines)
    preserved_count = len(preserved)
    pct = 100.0 if live_count == 0 else round((preserved_count / live_count) * 100, 2)

    return ContentLossReport(
        target_id=live_path.parent.name,
        target_kind="skill" if live_path.name == "SKILL.md" else "agent",
        live_path=str(live_path),
        rendered_path=str(rendered_path or "<preview>"),
        live_line_count=live_count,
        preserved_line_count=preserved_count,
        preservation_pct=pct,
        lines_lost=sorted(live_lines - rendered_lines),
        lines_added=sorted(rendered_lines - live_lines),
        passed=pct >= 90.0,
        computed_at=now_iso(),
    )
