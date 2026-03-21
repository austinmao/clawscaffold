"""Output manifest planning for rendered targets."""

from __future__ import annotations

from pathlib import Path

from clawscaffold.models import FileWriteEntry, OutputManifest, ResolvedManifest
from clawscaffold.utils import generated_target_dir, runtime_target_dir


def _supports_compiler_management(runtime_path: Path) -> bool:
    if not runtime_path.exists():
        return True
    return "<!-- oc:section" in runtime_path.read_text(encoding="utf-8")


def build_output_manifest(
    resolved: ResolvedManifest,
    rendered_files: dict[str, str] | None = None,
) -> OutputManifest:
    rendered_files = rendered_files or {}
    generated_dir = generated_target_dir(resolved.kind, resolved.target_id)
    runtime_dir = runtime_target_dir(resolved.kind, resolved.target_id)
    files = []
    if resolved.kind == "agent":
        workspace_files = set(resolved.resolved.get("agent", {}).get("workspace_files", []))
        files.append(
            FileWriteEntry(
                generated_path=str(generated_dir / "SOUL.md"),
                runtime_path=str(runtime_dir / "SOUL.md"),
                ownership_class="hybrid",
                content=rendered_files.get("SOUL.md", ""),
                source=resolved.resolved.get("target_source", ""),
            )
        )
        agents_path = runtime_dir / "AGENTS.md"
        if "AGENTS.md" in workspace_files and _supports_compiler_management(agents_path):
            files.append(
                FileWriteEntry(
                    generated_path=str(generated_dir / "AGENTS.md"),
                    runtime_path=str(agents_path),
                    ownership_class="generated",
                    content=rendered_files.get("AGENTS.md", ""),
                    source=resolved.resolved.get("target_source", ""),
                )
            )
        heartbeat_path = runtime_dir / "HEARTBEAT.md"
        if (
            resolved.resolved.get("agent", {}).get("heartbeat", {}).get("enabled")
            and "HEARTBEAT.md" in workspace_files
            and _supports_compiler_management(heartbeat_path)
        ):
            files.append(
                FileWriteEntry(
                    generated_path=str(generated_dir / "HEARTBEAT.md"),
                    runtime_path=str(heartbeat_path),
                    ownership_class="generated",
                    content=rendered_files.get("HEARTBEAT.md", ""),
                    source=resolved.resolved.get("target_source", ""),
                )
            )
        tools_path = runtime_dir / "TOOLS.md"
        if "TOOLS.md" in workspace_files and _supports_compiler_management(tools_path):
            files.append(
                FileWriteEntry(
                    generated_path=str(generated_dir / "TOOLS.md"),
                    runtime_path=str(tools_path),
                    ownership_class="hybrid",
                    content=rendered_files.get("TOOLS.md", ""),
                    source=resolved.resolved.get("target_source", ""),
                )
            )
    else:
        files.append(
            FileWriteEntry(
                generated_path=str(generated_dir / "SKILL.md"),
                runtime_path=str(runtime_dir / "SKILL.md"),
                ownership_class="hybrid",
                content=rendered_files.get("SKILL.md", ""),
                source=resolved.resolved.get("target_source", ""),
            )
        )
    config_ops = resolved.resolved.get("_config_ops", [])
    return OutputManifest(target_id=resolved.target_id, kind=resolved.kind, files=files, config_ops=config_ops)
