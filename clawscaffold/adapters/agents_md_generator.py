"""Generate agents/<key>/AGENTS.md from SOUL.md files."""

from __future__ import annotations

from pathlib import Path

from .hierarchy_reader import MergedAgent


def _find_soul_md(agent: MergedAgent, repo_root: Path) -> Path | None:
    """Find the SOUL.md file for an agent.

    Searches:
    1. agents/<domain>/<name>/SOUL.md (catalog ID based path)
    """
    # catalog ID is like "executive/cmo" -> agents/executive/cmo/SOUL.md
    soul_path = repo_root / "agents" / agent.id / "SOUL.md"
    if soul_path.is_file():
        return soul_path
    return None


def generate_agents_md(
    agents: list[MergedAgent],
    repo_root: Path,
    output_dir: Path,
) -> list[str]:
    """Generate AGENTS.md files with Paperclip frontmatter.

    For each agent, reads SOUL.md and writes agents/<key>/AGENTS.md
    with frontmatter containing name and title.

    Args:
        agents: List of merged agent specs.
        repo_root: Repository root directory.
        output_dir: Temp directory to write AGENTS.md files into.

    Returns:
        List of warnings for agents with missing SOUL.md.
    """
    warnings: list[str] = []

    for agent in agents:
        soul_path = _find_soul_md(agent, repo_root)

        if soul_path is None:
            warnings.append(
                f"WARNING: No SOUL.md found for {agent.id} — registering without instructions"
            )
            soul_content = f"# {agent.display_name or agent.title}\n\nNo SOUL.md found.\n"
        else:
            soul_content = soul_path.read_text()

        # Build AGENTS.md with frontmatter
        frontmatter = (
            f'---\nname: "{agent.display_name or agent.title}"\ntitle: "{agent.title}"\n---\n\n'
        )
        agents_md_content = frontmatter + soul_content

        # Write to output_dir/agents/<key>/AGENTS.md
        agent_dir = output_dir / "agents" / agent.key
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "AGENTS.md").write_text(agents_md_content)

    return warnings
