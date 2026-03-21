"""Shared constants for the spec-first scaffolder."""

from __future__ import annotations

RUN_STATES = [
    "proposed",
    "drafted",
    "reviewed",
    "approved_for_apply",
    "rendered",
    "validated",
    "applied",
    "refreshed",
    "qa_passed",
    "completed",
    "blocked",
    "rollback_pending",
    "rolled_back",
]

STATE_TRANSITIONS = {
    "proposed": {"drafted", "blocked"},
    "drafted": {"reviewed", "blocked"},
    "reviewed": {"approved_for_apply", "blocked"},
    "approved_for_apply": {"rendered", "blocked"},
    "rendered": {"validated", "blocked"},
    "validated": {"applied", "blocked"},
    "applied": {"refreshed", "rollback_pending"},
    "refreshed": {"qa_passed", "rollback_pending"},
    "qa_passed": {"completed"},
    "completed": set(),
    "blocked": {"rollback_pending", "proposed"},
    "rollback_pending": {"rolled_back", "blocked"},
    "rolled_back": set(),
}

REQUIRED_SOUL_SECTIONS = [
    "Who I Am",
    "Core Principles",
    "Boundaries",
    "Communication Style",
    "Security Rules",
    "Memory",
]

SOUL_SECTION_ORDER = [
    ("who_i_am", "Who I Am"),
    ("core_principles", "Core Principles"),
    ("boundaries", "Boundaries"),
    ("communication_style", "Communication Style"),
    ("security_rules", "Security Rules"),
    ("memory", "Memory"),
]

SOUL_SECTION_IDS = {heading: section_id for section_id, heading in SOUL_SECTION_ORDER}
SOUL_HEADINGS_BY_ID = {section_id: heading for section_id, heading in SOUL_SECTION_ORDER}

STANDARD_SKILL_SECTION_ORDER = [
    ("overview", "Overview"),
    ("usage", "Usage"),
    ("triggers", "Triggers"),
    ("requirements", "Requirements"),
]

STANDARD_SKILL_SECTION_IDS = {heading.lower(): section_id for section_id, heading in STANDARD_SKILL_SECTION_ORDER}

# Full canonical section set — enforced only after scaffold adopt
CANONICAL_SOUL_SECTION_ORDER = [
    ("who_i_am", "Who I Am"),
    ("core_principles", "Core Principles"),
    ("boundaries", "Boundaries"),
    ("scope_limits", "Scope Limits"),
    ("communication_style", "Communication Style"),
    ("channels", "Channels"),
    ("escalation", "Escalation"),
    ("security_rules", "Security Rules"),
    ("session_initialization", "Session Initialization"),
    ("memory", "Memory"),
]

CANONICAL_SOUL_SECTION_IDS = {heading: sid for sid, heading in CANONICAL_SOUL_SECTION_ORDER}

# Canonical skill sections — enforced after scaffold adopt
CANONICAL_SKILL_SECTION_ORDER = [
    ("purpose", "Purpose"),
    ("instructions", "Instructions"),
    ("inputs", "Inputs"),
    ("outputs", "Outputs"),
    ("error_handling", "Error Handling"),
]

CANONICAL_SKILL_SECTION_IDS = {heading.lower(): sid for sid, heading in CANONICAL_SKILL_SECTION_ORDER}

SKILL_FRONTMATTER_REQUIRED = ["name", "description", "permissions"]

DEFAULT_PROFILES = [
    "base/standard",
    "security/standard",
    "qa/standard",
    "memory/standard",
]

PROFILE_PRIORITY = {
    "base": 10,
    "archetype": 20,
    "security": 30,
    "qa": 40,
    "memory": 50,
    "channel": 60,
    "cognition": 60,
    "docs": 60,
    "execution": 60,
    "integrations": 60,
    "tenant": 90,
}

OWNERSHIP_CLASSES = ("generated", "hybrid", "scaffolded")

MANAGED_REGISTRY_FILENAME = "managed-paths.json"
ADOPTION_REGISTRY_FILENAME = "adoption-registry.json"

BOOTSTRAP_REGISTRY = [
    "compiler/engine",
    "compiler/schemas",
    "compiler/templates",
    "compiler/ownership",
    "scripts/hooks/spec-managed-guard.py",
    "scripts/hooks/spec-managed-guard-claude.json",
]
