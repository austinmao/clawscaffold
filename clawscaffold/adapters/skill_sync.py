"""Sync skills to agent workspace directories based on catalog declarations.

Reads skill-to-agent mappings from interview.json files and fallback tables,
then copies skill directories into each agent's workspace.

OpenClaw rejects symlinks that resolve outside the workspace root, so real
copies are used. The source of truth is always ``skills/<dept>/<name>/SKILL.md``
in the repo root.
"""

from __future__ import annotations

import filecmp
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ─── Fallback skill mappings (agents without interview data) ──────────────────
_CEO_SKILLS = [
    "pipeline-routing", "pipeline-dispatch", "governance-projection",
    "delegation", "reasoning-router", "intent-routing",
]

_FALLBACK_SKILLS: dict[str, list[str]] = {
    "content/copywriter": [
        "email-copy", "sms-copy", "copy-editing", "transformation-story",
        "ux-writing", "seo-geo-writing", "long-form-content", "humanizer",
        "brand-standards", "voice-calibration", "copywriting",
    ],
    "engineering/email-engineer": [
        "react-email-templates", "email-design-system", "email-campaign-html",
        "email-audit", "dark-mode-email", "render-react-email-assets",
        "deliverability", "resend",
    ],
    "engineering/frontend-engineer": [
        "nextjs-app-router", "tailwind-design-system", "react-state-management",
        "component-library", "form-building", "auth-frontend",
        "api-client-integration", "site-architecture", "frontend",
    ],
    "executive/ceo": _CEO_SKILLS,
    "executive/cco": [
        "brand-strategy", "brand-standards", "brand-review-gate",
        "brand-identity-design", "brand-compliance",
    ],
    "executive/cto": [
        "architecture-review", "dependency-modernization",
        "security-best-practices",
    ],
    "executive/cmo": [
        "website-build-orchestration", "pipeline-orchestration",
        "campaign-strategy", "funnel-strategy",
    ],
    "operations/coordinator": [
        "zoho-sign", "typeform", "airtable-participants",
        "org-config", "retry-gate", "slack",
    ],
    "operations/knowledge-sync": [
        "corpus-organizer", "corpus-triage", "memory-routing",
    ],
    "operations/transcript-curator": [
        "corpus-organizer", "corpus-triage", "corpus-formatter",
        "memory-routing",
    ],
    "sales/director": [
        "classify-intent", "qualify-lead", "response-compose",
        "extract-profile", "faq-lookup", "handoff-summary",
        "handoff-to-human", "invite-to-imessage", "memory-update",
        "sms-outreach", "deal-management",
    ],
    "finance/payroll": [
        "gusto", "stripe-integration",
    ],
}

_SKIP_NAMES = frozenset({
    "topic", "event_date", "launch_date", "campaign_slug",
    "page_slug", "pipeline_id", "lobster", "argsJson",
    "pipeline", "specced", "pending-review", "approved",
    "handed-off", "confirm", "confirm_all",
})


@dataclass
class SkillSyncResult:
    """Result of a skill sync operation."""
    agents_synced: int = 0
    copied: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)
    agent_details: list[dict[str, Any]] = field(default_factory=list)


def _extract_interview_skills(interview_path: Path) -> list[str]:
    """Extract authorized skill names from interview.json answers."""
    try:
        with open(interview_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    skills: list[str] = []
    answers = data.get("answers", {})
    for val in answers.values():
        content = ""
        if isinstance(val, dict):
            content = val.get("content", "")
        elif isinstance(val, str):
            content = val
        if not content:
            continue
        if "skill" in content.lower() or "invoke" in content.lower():
            found = re.findall(r"`([a-z0-9][\w-]*)`", content)
            skills.extend(
                s for s in found if s not in _SKIP_NAMES and len(s) > 2
            )
    return skills


def build_agent_skill_map(repo_root: Path) -> dict[str, list[str]]:
    """Build agent → skills mapping from catalog interviews + fallbacks."""
    catalog_dir = repo_root / "catalog" / "agents"
    mapping: dict[str, list[str]] = {}

    if catalog_dir.is_dir():
        for interview_path in sorted(catalog_dir.rglob("*.interview.json")):
            agent_name = interview_path.stem.replace(".interview", "")
            department = interview_path.parent.name
            catalog_id = f"{department}/{agent_name}"
            skills = _extract_interview_skills(interview_path)
            if skills:
                mapping[catalog_id] = skills

    for catalog_id, skills in _FALLBACK_SKILLS.items():
        if catalog_id not in mapping:
            mapping[catalog_id] = list(skills)
        else:
            existing = set(mapping[catalog_id])
            for s in skills:
                if s not in existing:
                    mapping[catalog_id].append(s)

    for catalog_id in mapping:
        mapping[catalog_id] = list(dict.fromkeys(mapping[catalog_id]))

    return mapping


def _find_skill_dir(skill_name: str, skills_dir: Path) -> Path | None:
    """Find a skill directory by name in the nested repo structure."""
    for skill_md in skills_dir.rglob("SKILL.md"):
        if skill_md.parent.name == skill_name:
            return skill_md.parent
    return None


def sync_skills(
    repo_root: Path,
    *,
    agent_filter: str | None = None,
    dry_run: bool = False,
    clean: bool = False,
) -> SkillSyncResult:
    """Sync skills from repo to agent workspace directories."""
    agents_dir = repo_root / "agents"
    skills_dir = repo_root / "skills"
    mapping = build_agent_skill_map(repo_root)
    result = SkillSyncResult()

    if agent_filter:
        if agent_filter not in mapping:
            result.errors.append(f"Agent '{agent_filter}' not in skill map")
            return result
        mapping = {agent_filter: mapping[agent_filter]}

    for catalog_id in sorted(mapping):
        workspace = agents_dir / catalog_id
        if not workspace.is_dir():
            continue

        skill_names = mapping[catalog_id]
        ws_skills_dir = workspace / "skills"
        agent_detail: dict[str, Any] = {"agent": catalog_id, "actions": []}

        if not dry_run and skill_names:
            ws_skills_dir.mkdir(exist_ok=True)

        for skill_name in skill_names:
            dest = ws_skills_dir / skill_name
            if dest.is_dir():
                src = _find_skill_dir(skill_name, skills_dir)
                if src and (dest / "SKILL.md").exists():
                    if filecmp.cmp(str(src / "SKILL.md"), str(dest / "SKILL.md"), shallow=False):
                        result.unchanged += 1
                        continue
                    if not dry_run:
                        shutil.rmtree(dest)
                        shutil.copytree(str(src), str(dest))
                    agent_detail["actions"].append({"skill": skill_name, "action": "updated"})
                    result.updated += 1
                else:
                    result.unchanged += 1
                continue

            src = _find_skill_dir(skill_name, skills_dir)
            if src is None:
                agent_detail["actions"].append({"skill": skill_name, "action": "not_found"})
                result.missing += 1
                continue

            if not dry_run:
                shutil.copytree(str(src), str(dest))
            agent_detail["actions"].append({"skill": skill_name, "action": "copied"})
            result.copied += 1

        if clean and ws_skills_dir.is_dir():
            declared = set(skill_names)
            for existing in sorted(ws_skills_dir.iterdir()):
                if existing.name not in declared and existing.is_dir():
                    if not dry_run:
                        shutil.rmtree(existing)
                    agent_detail["actions"].append({"skill": existing.name, "action": "removed"})
                    result.removed += 1

        result.agent_details.append(agent_detail)
        result.agents_synced += 1

    return result
