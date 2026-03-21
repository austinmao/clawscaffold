"""Detection helpers for ClawSpec integration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from clawscaffold.section_parser import parse_sections, parse_skill_sections

_AGENT_SUPPLEMENTS = ("AGENTS.md", "USER.md", "TOOLS.md", "HEARTBEAT.md", "IDENTITY.md", "BOOTSTRAP.md")
_SKILL_SUPPLEMENTS = ("README.md", "AGENTS.md", "TOOLS.md", "IDENTITY.md", "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md")
_DELEGATE_TO_RE = re.compile(r"\b[Dd]elegate to\s+(agents|skills)/([A-Za-z0-9/_-]+)")
_INVOKE_RE = re.compile(r"\binvoke\s+(skills)/([A-Za-z0-9/_-]+)")
_SESSIONS_SPAWN_RE = re.compile(r"\bsessions_spawn\b")
_PHASE_HEADING_RE = re.compile(r"^##\s+(?:Phase|Stage)\s+\d+\s*:\s*(.+?)\s*$", re.MULTILINE)
_NUMBERED_STEP_RE = re.compile(r"^\d+\.\s+(.+?)\s*$", re.MULTILINE)


def _target_root(kind: str, target_id: str, root: Path) -> Path:
    return root / ("agents" if kind == "agent" else "skills") / target_id


def _parse_sections(kind: str, text: str) -> list[Any]:
    if kind == "agent":
        return parse_sections(text)
    _frontmatter, sections = parse_skill_sections(text)
    return sections


def load_instruction_sources(target_kind: str, target_id: str, root: Path) -> list[dict[str, Any]]:
    target_root = _target_root(target_kind, target_id, root)
    if not target_root.exists():
        return []

    names = [("SOUL.md" if target_kind == "agent" else "SKILL.md")]
    names.extend(_AGENT_SUPPLEMENTS if target_kind == "agent" else _SKILL_SUPPLEMENTS)

    sources: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for name in names:
        path = target_root / name
        if not path.exists() or path in seen:
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8")
        sources.append(
            {
                "path": str(path),
                "name": name,
                "text": text,
                "sections": _parse_sections(target_kind, text),
            }
        )
    return sources


def detect_delegations(target_kind: str, target_id: str, root: Path) -> list[dict[str, Any]]:
    delegations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for source in load_instruction_sources(target_kind, target_id, root):
        text = source["text"]
        for pattern in (_DELEGATE_TO_RE, _INVOKE_RE):
            for match in pattern.finditer(text):
                kind_dir, delegate_id = match.groups()
                delegate_kind = "agent" if kind_dir == "agents" else "skill"
                key = (delegate_kind, delegate_id)
                if key in seen:
                    continue
                seen.add(key)
                delegations.append(
                    {
                        "target_kind": delegate_kind,
                        "target_id": delegate_id,
                        "source_path": source["path"],
                        "source_name": source["name"],
                        "pattern": match.group(0),
                    }
                )
        if _SESSIONS_SPAWN_RE.search(text):
            key = ("workflow", "sessions_spawn")
            if key not in seen:
                seen.add(key)
                delegations.append(
                    {
                        "target_kind": "skill",
                        "target_id": "sessions_spawn",
                        "source_path": source["path"],
                        "source_name": source["name"],
                        "pattern": "sessions_spawn",
                    }
                )
    return delegations


def detect_pipeline_stages(target_kind: str, target_id: str, root: Path) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for source in load_instruction_sources(target_kind, target_id, root):
        text = source["text"]
        phase_matches = list(_PHASE_HEADING_RE.finditer(text))
        if not phase_matches:
            continue
        for index, match in enumerate(phase_matches):
            start = match.end()
            end = phase_matches[index + 1].start() if index + 1 < len(phase_matches) else len(text)
            body = text[start:end]
            for step_match in _NUMBERED_STEP_RE.finditer(body):
                stages.append(
                    {
                        "name": step_match.group(1).strip(),
                        "phase": match.group(1).strip(),
                        "source_path": source["path"],
                    }
                )
        if stages:
            return stages
    return stages


def detect_sub_skills(target_id: str, root: Path) -> list[str]:
    subskills_root = root / "skills" / target_id / "sub-skills"
    if not subskills_root.exists():
        return []
    found = []
    for skill_file in sorted(subskills_root.glob("*/SKILL.md")):
        found.append(str(skill_file.parent.relative_to(root / "skills")))
    return found


def detect_target_tier(kind: str, target_id: str, spec: dict[str, Any], root: Path) -> str:
    explicit = spec.get("tier")
    if isinstance(explicit, str) and explicit:
        return explicit

    if kind == "agent":
        if target_id.startswith("builder/"):
            return "orchestrator"
        return "interior-agent"

    if detect_sub_skills(target_id, root):
        return "orchestrator"
    if detect_pipeline_stages(kind, target_id, root):
        return "orchestrator"

    sources = load_instruction_sources(kind, target_id, root)
    combined = "\n".join(source["text"] for source in sources).lower()
    if any(token in combined for token in ("slack", "email", "sms", "whatsapp", "discord", "webhook", "api")):
        return "boundary-skill"
    return "interior-skill"
