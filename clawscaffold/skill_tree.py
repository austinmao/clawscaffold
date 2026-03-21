"""
Capability tree generator.

Auto-generates a hierarchical capability tree from the workspace skills/ directory.
Each node in the tree represents a directory level; leaf nodes reference SKILL.md files.

Output conforms to the CapabilityTreeNode schema from specs/002-multi-agent-context/data-model.md.

Usage:
    from clawscaffold.skill_tree import build_capability_tree
    tree = build_capability_tree()  # builds from repo root / skills/
    import json; print(json.dumps(tree, indent=2))
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from clawscaffold.paths import repo_root


# Top-level departments as defined in the workspace taxonomy.
# Discovery is driven by actual directory scan — this list is used only for
# ordering and completeness reporting, not as a hard-coded filter.
EXPECTED_DEPARTMENTS = [
    "creative",
    "content",
    "engineering",
    "strategy",
    "campaigns",
    "quality",
    "executive",
    "operations",
    "platform",
    "finance",
    "marketing",
    "sales",
    "programs",
    "qa",
    "newsletter",
]


def _parse_frontmatter(skill_md_path: Path) -> dict[str, Any]:
    """
    Parse the YAML frontmatter block from a SKILL.md file.
    Returns a dict with at minimum 'name' and 'description' keys.
    Returns empty dict if the file has no valid frontmatter.
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    # YAML frontmatter is delimited by --- on the first line
    if not text.startswith("---"):
        return {}

    # Find the closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}

    fm_text = text[3:end].strip()
    result: dict[str, Any] = {}

    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in ("name", "description", "version"):
            result[key] = value
        elif key == "filesystem":
            result.setdefault("permissions", {})["filesystem"] = value
        elif key == "network":
            result.setdefault("permissions", {})["network"] = value == "true"

    return result


def _build_skill_ref(skill_md_path: Path, skills_root: Path) -> dict[str, Any]:
    """Build a SkillRef dict from a SKILL.md path."""
    fm = _parse_frontmatter(skill_md_path)
    rel_path = str(skill_md_path.relative_to(skills_root.parent))

    return {
        "name": fm.get("name") or skill_md_path.parent.name,
        "description": fm.get("description", ""),
        "path": rel_path,
        "permissions": fm.get("permissions", {"filesystem": "none", "network": False}),
        # Local workspace skills are always treated as local-built.
        "source": "local-built",
        # Scan status defaults to 'clean' for workspace skills (built locally per policy).
        "scan_status": "clean",
        "operator_reviewed": True,
        # Install history is unknown at generation time; default to 0 to be conservative.
        "install_history_days": 0,
        # Trust score computed by skill_catalog.py; placeholder here.
        "trust_score": 1.0,
    }


def _walk_directory(
    directory: Path,
    skills_root: Path,
    depth: int = 0,
) -> dict[str, Any]:
    """
    Recursively walk a directory and produce a CapabilityTreeNode.

    Args:
        directory: Current directory to scan.
        skills_root: Root of the skills/ directory.
        depth: Current depth (0 = top-level department).

    Returns:
        A CapabilityTreeNode dict.
    """
    node: dict[str, Any] = {
        "name": directory.name,
        "path": str(directory.relative_to(skills_root)),
        "depth": depth,
        "description": "",
        "child_count": 0,
        "skill_count": 0,
        "children": [],
        "skills": [],
    }

    skill_md = directory / "SKILL.md"
    if skill_md.exists():
        # This directory is a skill leaf — add the skill ref and return.
        ref = _build_skill_ref(skill_md, skills_root)
        node["description"] = ref["description"]
        node["skills"] = [ref]
        node["skill_count"] = 1
        return node

    # Walk subdirectories
    try:
        entries = sorted(directory.iterdir())
    except PermissionError:
        return node

    descriptions: list[str] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        # Skip hidden directories and __pycache__
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue

        child = _walk_directory(entry, skills_root, depth + 1)
        if child["skill_count"] == 0 and not child["children"]:
            # Empty subtree — skip
            continue

        node["children"].append(child)
        node["skill_count"] += child["skill_count"]
        if child["description"]:
            descriptions.append(child["description"])

    node["child_count"] = len(node["children"])
    # Aggregate description from first 3 child descriptions
    if descriptions:
        node["description"] = "; ".join(descriptions[:3])
        if len(descriptions) > 3:
            node["description"] += f" (+{len(descriptions) - 3} more)"

    return node


def build_capability_tree(skills_dir: Path | None = None) -> dict[str, Any]:
    """
    Build a capability tree from the workspace skills/ directory.

    Args:
        skills_dir: Path to the skills/ root. Defaults to <repo_root>/skills/.

    Returns:
        A CapabilityTreeNode dict representing the full skills tree.
        The root node has name='skills' and depth=-1 (meta-root).
    """
    if skills_dir is None:
        skills_dir = repo_root() / "skills"

    if not skills_dir.exists():
        return {
            "name": "skills",
            "path": "skills",
            "depth": -1,
            "description": "No skills directory found",
            "child_count": 0,
            "skill_count": 0,
            "children": [],
            "skills": [],
        }

    root: dict[str, Any] = {
        "name": "skills",
        "path": "skills",
        "depth": -1,
        "description": "OpenClaw workspace skill capability tree",
        "child_count": 0,
        "skill_count": 0,
        "children": [],
        "skills": [],
    }

    # Build ordered department list: expected departments first, then any extras
    try:
        all_dirs = sorted(d for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    except PermissionError:
        return root

    ordered = [d for d in all_dirs if d.name in EXPECTED_DEPARTMENTS]
    extras = [d for d in all_dirs if d.name not in EXPECTED_DEPARTMENTS]

    for dept_dir in ordered + extras:
        dept_node = _walk_directory(dept_dir, skills_dir, depth=0)
        if dept_node["skill_count"] > 0 or dept_node["children"]:
            root["children"].append(dept_node)
            root["skill_count"] += dept_node["skill_count"]

    root["child_count"] = len(root["children"])
    return root


def find_skills(
    query: str,
    tree: dict[str, Any] | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """
    Search the capability tree for skills matching a query string.

    Matches against skill name and description (case-insensitive).
    Returns a list of SkillRef dicts sorted by relevance (exact name match first,
    then description contains, then partial word match).

    Args:
        query: Natural language query (e.g., "send email via resend").
        tree: Pre-built capability tree. If None, builds from disk.
        max_results: Maximum number of results to return.

    Returns:
        List of SkillRef dicts with an added 'match_reason' field.
    """
    if tree is None:
        tree = build_capability_tree()

    query_lower = query.lower()
    query_words = set(re.split(r"\W+", query_lower)) - {"", "via", "the", "a", "an", "for", "to"}

    results: list[tuple[int, dict[str, Any]]] = []  # (score, skill_ref)

    def _collect_skills(node: dict[str, Any]) -> None:
        for skill in node.get("skills", []):
            name = skill.get("name", "").lower()
            desc = skill.get("description", "").lower()
            score = 0
            reason = ""

            if query_lower in name:
                score = 100
                reason = "exact name match"
            elif query_lower in desc:
                score = 80
                reason = "description match"
            else:
                word_hits = sum(1 for w in query_words if w in name or w in desc)
                if word_hits > 0:
                    score = 10 + word_hits * 15
                    reason = f"{word_hits} keyword(s) matched"

            if score > 0:
                ref = dict(skill)
                ref["match_reason"] = reason
                results.append((score, ref))

        for child in node.get("children", []):
            _collect_skills(child)

    _collect_skills(tree)

    # Sort by score descending, then name
    results.sort(key=lambda x: (-x[0], x[1].get("name", "")))
    return [ref for _, ref in results[:max_results]]
