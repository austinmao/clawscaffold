"""
Skill catalog — trust score computation and metadata enrichment.

Parses skill permissions from SKILL.md frontmatter, merges scan status,
operator review status, and install history, then computes a trust_score
per the SkillRef schema in specs/002-multi-agent-context/data-model.md.

Trust score formula (0.0 – 1.0):
  Source verification (0.3):
    local-built   → 1.0
    scanned-external → 0.7
    unscanned     → 0.0
  Scan result (0.3):
    clean         → 1.0
    warnings      → 0.5
    blocked       → 0.0
    unknown       → 0.3
  Operator review (0.2):
    reviewed      → 1.0
    unreviewed    → 0.0
  Install history (0.2):
    >30 days      → 1.0
    >7 days       → 0.7
    ≤7 days (new) → 0.5

Usage:
    from clawscaffold.skill_catalog import build_catalog, compute_trust_score
    catalog = build_catalog()          # builds from disk
    for entry in catalog:
        print(entry["name"], entry["trust_score"])
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from clawscaffold.paths import repo_root
from clawscaffold.skill_tree import build_capability_tree, find_skills


# --- Trust score weights (must sum to 1.0) ---
_W_SOURCE = 0.3
_W_SCAN = 0.3
_W_REVIEW = 0.2
_W_HISTORY = 0.2

# --- Source scores ---
_SOURCE_SCORES: dict[str, float] = {
    "local-built": 1.0,
    "scanned-external": 0.7,
    "clawhub": 0.0,  # ClawHub unreviewed — not trusted per security policy
    "github": 0.7,
    "other": 0.5,
    "unscanned": 0.0,
}

# --- Scan result scores ---
_SCAN_SCORES: dict[str, float] = {
    "clean": 1.0,
    "warnings": 0.5,
    "blocked": 0.0,
    "unknown": 0.3,
}

# Suspicious patterns in SKILL.md that lower scan status automatically
_TOXIC_PATTERNS = [
    r"shell\.execute",
    r"fs\.read_root",
    r"clawhub\s+install",
    r"91\.92\.242\.30",        # ClawHavoc C2 IP
    r"mediafire\.com",
    r"mega\.nz",
    r"base64.*decode",
    r"eval\(",
]
_TOXIC_RE = [re.compile(p, re.IGNORECASE) for p in _TOXIC_PATTERNS]

# Warning patterns (lower score but don't block)
_WARNING_PATTERNS = [
    r"filesystem:\s*write",    # Write access is elevated — not toxic but warrants review
    r"shell\.",
    r"\.clawhub",
]
_WARNING_RE = [re.compile(p, re.IGNORECASE) for p in _WARNING_PATTERNS]


def scan_skill_md(skill_md_path: Path) -> str:
    """
    Static scan of a SKILL.md file for toxic and warning patterns.

    Returns:
        "clean"    — no suspicious patterns found
        "warnings" — elevated-permission patterns found but no toxic patterns
        "blocked"  — toxic patterns found (shell.execute without need, C2 IPs, etc.)
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError:
        return "unknown"

    for pattern in _TOXIC_RE:
        if pattern.search(text):
            return "blocked"

    for pattern in _WARNING_RE:
        if pattern.search(text):
            return "warnings"

    return "clean"


def compute_trust_score(
    source: str = "local-built",
    scan_status: str = "clean",
    operator_reviewed: bool = True,
    install_history_days: int = 0,
) -> float:
    """
    Compute trust score from individual factors.

    Args:
        source: Where the skill originated (local-built, clawhub, github, etc.)
        scan_status: Result of security scan (clean, warnings, blocked, unknown)
        operator_reviewed: Whether an operator has explicitly reviewed this skill
        install_history_days: Days the skill has been installed without incident

    Returns:
        Float in [0.0, 1.0]. Blocked skills always score 0.0.
    """
    if scan_status == "blocked":
        return 0.0

    source_score = _SOURCE_SCORES.get(source, 0.5)
    scan_score = _SCAN_SCORES.get(scan_status, 0.3)
    review_score = 1.0 if operator_reviewed else 0.0

    if install_history_days > 30:
        history_score = 1.0
    elif install_history_days > 7:
        history_score = 0.7
    else:
        history_score = 0.5

    raw = (
        source_score * _W_SOURCE
        + scan_score * _W_SCAN
        + review_score * _W_REVIEW
        + history_score * _W_HISTORY
    )
    return round(min(max(raw, 0.0), 1.0), 3)


def build_catalog(
    skills_dir: Path | None = None,
    scan_all: bool = True,
) -> list[dict[str, Any]]:
    """
    Build the full skill catalog from the workspace skills/ directory.

    Scans each SKILL.md for toxic patterns, computes trust score,
    and returns a flat list of SkillRef dicts (sorted by trust_score desc, name asc).

    Args:
        skills_dir: Path to the skills/ root. Defaults to <repo_root>/skills/.
        scan_all: If True, run static scan on every SKILL.md.

    Returns:
        List of enriched SkillRef dicts with trust_score populated.
    """
    if skills_dir is None:
        skills_dir = repo_root() / "skills"

    tree = build_capability_tree(skills_dir)

    catalog: list[dict[str, Any]] = []

    def _collect(node: dict[str, Any]) -> None:
        for skill in node.get("skills", []):
            ref = dict(skill)
            skill_path = skills_dir.parent / ref["path"]

            if scan_all and skill_path.exists():
                ref["scan_status"] = scan_skill_md(skill_path)
            elif "scan_status" not in ref:
                ref["scan_status"] = "unknown"

            # Re-compute trust score with actual scan result
            ref["trust_score"] = compute_trust_score(
                source=ref.get("source", "local-built"),
                scan_status=ref["scan_status"],
                operator_reviewed=ref.get("operator_reviewed", True),
                install_history_days=ref.get("install_history_days", 0),
            )

            catalog.append(ref)

        for child in node.get("children", []):
            _collect(child)

    _collect(tree)

    catalog.sort(key=lambda s: (-s["trust_score"], s.get("name", "")))
    return catalog


def search_catalog(
    query: str,
    catalog: list[dict[str, Any]] | None = None,
    min_trust_score: float = 0.0,
    max_results: int = 10,
    skills_dir: "Path | None" = None,
) -> list[dict[str, Any]]:
    """
    Search the skill catalog for skills matching a query.

    When a pre-built catalog is provided, searches within it directly
    (no disk rebuild). When catalog is None, builds from skills_dir or
    the default workspace skills/ directory.

    Args:
        query: Natural language query string.
        catalog: Pre-built catalog list. If None, builds from disk.
        min_trust_score: Filter out skills below this trust score.
        max_results: Maximum number of results.
        skills_dir: Override the skills directory for tree building.

    Returns:
        List of matching SkillRef dicts (trust_score ≥ min_trust_score),
        sorted by relevance then trust_score descending.
    """
    if catalog is None:
        catalog = build_catalog(skills_dir)

    # Search directly within the provided catalog (avoids mismatch between
    # catalog paths and real-disk tree when testing with fixture data).
    query_lower = query.lower()
    query_words = set(re.split(r"\W+", query_lower)) - {"", "via", "the", "a", "an", "for", "to"}

    results: list[tuple[int, dict[str, Any]]] = []
    for skill in catalog:
        name = skill.get("name", "").lower()
        desc = skill.get("description", "").lower()
        trust = skill.get("trust_score", 1.0)

        if trust < min_trust_score:
            continue

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

    results.sort(key=lambda x: (-x[0], -x[1].get("trust_score", 0), x[1].get("name", "")))
    return [ref for _, ref in results[:max_results]]


def format_skill_result(skill: dict[str, Any], show_permissions: bool = True) -> str:
    """Format a SkillRef as a human-readable string for CLI output."""
    lines = [
        f"  {skill.get('name', 'unknown')} — {skill.get('description', '')}",
        f"    path: {skill.get('path', '')}",
        f"    trust: {skill.get('trust_score', 0):.2f} | scan: {skill.get('scan_status', '?')} | source: {skill.get('source', '?')}",
    ]
    if show_permissions:
        perms = skill.get("permissions", {})
        lines.append(
            f"    permissions: filesystem={perms.get('filesystem', 'none')} network={perms.get('network', False)}"
        )
    if reason := skill.get("match_reason"):
        lines.append(f"    match: {reason}")
    return "\n".join(lines)
