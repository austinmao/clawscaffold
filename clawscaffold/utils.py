"""Internal utility helpers used across compiler modules."""

from __future__ import annotations

import json
import random
import re
import string
from collections.abc import Iterable
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from clawscaffold.paths import repo_root

_OC_SECTION_MARKER_LINE_RE = re.compile(r'^\s*<!--\s*/?oc:section id="[^"]+"[^>]*-->\s*$\n?', re.MULTILINE)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sha256_prefix(text: str, length: int = 12) -> str:
    return sha256(text.encode("utf-8")).hexdigest()[:length]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in YAML file: {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=False)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def repo_rel(path: Path) -> str:
    return str(path.resolve().relative_to(repo_root()))


def slug_to_title(slug: str) -> str:
    tokens = [token for token in re.split(r"[/_-]+", slug) if token]
    return " ".join(token.capitalize() for token in tokens) or "Untitled"


def run_id(action: str) -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{action}-{datetime.now(timezone.utc):%Y%m%d}-{suffix}"


def deep_merge(base: Any, incoming: Any) -> Any:
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = dict(base)
        for key, value in incoming.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else value
        return merged
    if isinstance(base, list) and isinstance(incoming, list):
        merged_list: list[Any] = []
        for item in [*base, *incoming]:
            if item not in merged_list:
                merged_list.append(item)
        return merged_list
    return incoming


def load_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    try:
        frontmatter = yaml.safe_load(parts[0][4:]) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, parts[1]


def dump_frontmatter(data: dict[str, Any], body: str) -> str:
    frontmatter = yaml.safe_dump(data, sort_keys=False, allow_unicode=False).strip()
    return f"---\n{frontmatter}\n---\n{body.lstrip()}"


def strip_managed_markers(text: str) -> str:
    return _OC_SECTION_MARKER_LINE_RE.sub("", text).strip("\n")


def iter_target_paths(root: Path | None = None) -> Iterable[Path]:
    base = root or repo_root()
    catalog_root = base / "catalog"
    if not catalog_root.exists():
        return []
    return sorted(catalog_root.rglob("*.yaml"))


def canonical_target_path(kind: str, target_id: str, root: Path | None = None) -> Path:
    base = root or repo_root()
    if kind == "agent":
        return base / "catalog" / "agents" / f"{target_id}.yaml"
    if kind == "tenant":
        return base / "catalog" / "tenants" / f"{target_id}.yaml"
    if kind == "brand":
        return base / "catalog" / "brands" / f"{target_id}.yaml"
    if kind == "site":
        return base / "catalog" / "sites" / f"{target_id}.yaml"
    return base / "catalog" / "skills" / f"{target_id}.yaml"


def runtime_target_dir(kind: str, target_id: str, root: Path | None = None) -> Path:
    base = root or repo_root()
    if kind == "agent":
        return base / "agents" / target_id
    if kind == "tenant":
        return base / "tenants" / target_id
    if kind == "brand":
        return base / "brands" / target_id
    if kind == "site":
        return base / "sites" / target_id
    return base / "skills" / target_id


def generated_target_dir(kind: str, target_id: str, root: Path | None = None) -> Path:
    base = root or repo_root()
    if kind == "agent":
        return base / "compiler" / "generated" / "agents" / target_id
    if kind == "tenant":
        return base / "compiler" / "generated" / "tenants" / target_id
    if kind == "brand":
        return base / "compiler" / "generated" / "brands" / target_id
    if kind == "site":
        return base / "compiler" / "generated" / "sites" / target_id
    return base / "compiler" / "generated" / "skills" / target_id


def upsert_marked_section(document: str, marker_id: str, content: str) -> str:
    start = f"<!-- oc:section id=\"{marker_id}\""
    end = f"<!-- /oc:section id=\"{marker_id}\" -->"
    lines = document.splitlines()
    start_index = next((i for i, line in enumerate(lines) if start in line), None)
    end_index = next((i for i, line in enumerate(lines) if end in line), None)
    if start_index is None or end_index is None or start_index >= end_index:
        separator = "\n" if document.endswith("\n") or not document else "\n\n"
        return f"{document.rstrip()}{separator}{content.rstrip()}\n"
    new_lines = lines[:start_index] + content.rstrip().splitlines() + lines[end_index + 1 :]
    return "\n".join(new_lines).rstrip() + "\n"
