"""Tests for SOUL.md -> AGENTS.md conversion."""

from __future__ import annotations

from pathlib import Path

from clawscaffold.adapters.agents_md_generator import generate_agents_md
from clawscaffold.adapters.hierarchy_reader import MergedAgent


def _make_agent(**overrides) -> MergedAgent:
    defaults = {
        "id": "executive/cmo",
        "key": "cmo",
        "gateway_agent_id": "agents-executive-cmo",
        "title": "Chief Marketing Officer",
        "display_name": "CMO",
        "description": "Orchestrates marketing",
        "emoji": "",
        "role": "pm",
        "reports_to_key": None,
        "budget_monthly_cents": 0,
        "heartbeat_enabled": False,
        "lifecycle_bridge": "not_enrolled",
        "timeout_sec": 60,
        "org_level": "executive",
        "manages": [],
    }
    defaults.update(overrides)
    return MergedAgent(**defaults)


class TestGenerateAgentsMd:
    def test_frontmatter_prepended(self, tmp_path: Path):
        # Create a SOUL.md
        soul_dir = tmp_path / "agents" / "executive" / "cmo"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("# Who I Am\n\nI am the CMO.\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agents = [_make_agent()]
        warnings = generate_agents_md(agents, tmp_path, output_dir)

        assert warnings == []
        agents_md = (output_dir / "agents" / "cmo" / "AGENTS.md").read_text()
        assert agents_md.startswith('---\nname: "CMO"\ntitle: "Chief Marketing Officer"\n---\n\n')
        assert "# Who I Am" in agents_md
        assert "I am the CMO." in agents_md

    def test_soul_content_preserved_verbatim(self, tmp_path: Path):
        soul_content = "# Who I Am\n\nSpecial chars: é, ñ, ü\n\n## Boundaries\n\n- Never do X\n"
        soul_dir = tmp_path / "agents" / "executive" / "cmo"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text(soul_content)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        generate_agents_md([_make_agent()], tmp_path, output_dir)
        agents_md = (output_dir / "agents" / "cmo" / "AGENTS.md").read_text()

        # Content should be present after frontmatter
        assert soul_content in agents_md

    def test_missing_soul_produces_warning(self, tmp_path: Path):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agents = [_make_agent()]
        warnings = generate_agents_md(agents, tmp_path, output_dir)

        assert len(warnings) == 1
        assert "No SOUL.md found for executive/cmo" in warnings[0]

        # File should still be created with placeholder
        agents_md = (output_dir / "agents" / "cmo" / "AGENTS.md").read_text()
        assert "No SOUL.md found." in agents_md

    def test_multiple_agents(self, tmp_path: Path):
        for agent_id in ["executive/cmo", "content/copywriter"]:
            soul_dir = tmp_path / "agents" / agent_id
            soul_dir.mkdir(parents=True)
            (soul_dir / "SOUL.md").write_text(f"# {agent_id}\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agents = [
            _make_agent(),
            _make_agent(
                id="content/copywriter", key="copywriter", title="Copywriter", display_name="Quill"
            ),
        ]
        warnings = generate_agents_md(agents, tmp_path, output_dir)

        assert warnings == []
        assert (output_dir / "agents" / "cmo" / "AGENTS.md").is_file()
        assert (output_dir / "agents" / "copywriter" / "AGENTS.md").is_file()

        quill_md = (output_dir / "agents" / "copywriter" / "AGENTS.md").read_text()
        assert 'name: "Quill"' in quill_md
        assert 'title: "Copywriter"' in quill_md

    def test_uses_display_name_over_title(self, tmp_path: Path):
        soul_dir = tmp_path / "agents" / "executive" / "cmo"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("# CMO\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agents = [_make_agent(display_name="Marketing Boss", title="Chief Marketing Officer")]
        generate_agents_md(agents, tmp_path, output_dir)

        agents_md = (output_dir / "agents" / "cmo" / "AGENTS.md").read_text()
        assert 'name: "Marketing Boss"' in agents_md

    def test_output_path_is_agents_key_agents_md(self, tmp_path: Path):
        """Output file must be written to agents/<key>/AGENTS.md."""
        soul_dir = tmp_path / "agents" / "content" / "copywriter"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("# Copywriter\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agent = _make_agent(
            id="content/copywriter", key="copywriter", title="Copywriter", display_name="Quill"
        )
        generate_agents_md([agent], tmp_path, output_dir)

        expected_path = output_dir / "agents" / "copywriter" / "AGENTS.md"
        assert expected_path.is_file(), f"Expected {expected_path} to exist"

    def test_frontmatter_name_and_title_format(self, tmp_path: Path):
        """Frontmatter must use quoted strings for name and title fields."""
        soul_dir = tmp_path / "agents" / "engineering" / "frontend-engineer"
        soul_dir.mkdir(parents=True)
        (soul_dir / "SOUL.md").write_text("# Nova\n\nI build frontends.\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agent = _make_agent(
            id="engineering/frontend-engineer",
            key="frontend-engineer",
            title="Frontend Engineer",
            display_name="Nova",
        )
        generate_agents_md([agent], tmp_path, output_dir)

        agents_md = (output_dir / "agents" / "frontend-engineer" / "AGENTS.md").read_text()

        # Both fields must appear with their YAML quoted-string format
        assert 'name: "Nova"' in agents_md
        assert 'title: "Frontend Engineer"' in agents_md

        # Frontmatter block must be delimited by --- markers
        lines = agents_md.splitlines()
        assert lines[0] == "---"
        assert "---" in lines[1:]  # closing delimiter present

    def test_missing_soul_md_with_monkeypatch_env(self, tmp_path: Path, monkeypatch):
        """Missing SOUL.md produces warning regardless of env configuration."""
        monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "dummy-token")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agents = [_make_agent()]
        warnings = generate_agents_md(agents, tmp_path, output_dir)

        assert len(warnings) == 1
        assert "WARNING" in warnings[0]
        assert "executive/cmo" in warnings[0]

        # Fallback AGENTS.md is still written
        agents_md_path = output_dir / "agents" / "cmo" / "AGENTS.md"
        assert agents_md_path.is_file()
        content = agents_md_path.read_text()
        assert 'name: "CMO"' in content
        assert "No SOUL.md found." in content

    def test_three_level_agents_output(self, tmp_path: Path):
        """Executive, lead, and specialist agents all get their own AGENTS.md files."""
        agent_specs = [
            ("executive/cmo", "cmo", "Chief Marketing Officer", "CMO"),
            ("engineering/frontend-engineer", "frontend-engineer", "Frontend Engineer", "Nova"),
            ("content/copywriter", "copywriter", "Copywriter", "Quill"),
        ]
        for agent_id, _key, title, display_name in agent_specs:
            soul_dir = tmp_path / "agents" / agent_id
            soul_dir.mkdir(parents=True)
            (soul_dir / "SOUL.md").write_text(f"# {display_name}\n\nI am the {title}.\n")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        agents = [
            _make_agent(
                id="executive/cmo",
                key="cmo",
                title="Chief Marketing Officer",
                display_name="CMO",
                org_level="executive",
            ),
            _make_agent(
                id="engineering/frontend-engineer",
                key="frontend-engineer",
                title="Frontend Engineer",
                display_name="Nova",
                org_level="lead",
            ),
            _make_agent(
                id="content/copywriter",
                key="copywriter",
                title="Copywriter",
                display_name="Quill",
                org_level="specialist",
            ),
        ]
        warnings = generate_agents_md(agents, tmp_path, output_dir)

        assert warnings == []
        for _agent_id, key, title, display_name in agent_specs:
            agents_md = (output_dir / "agents" / key / "AGENTS.md").read_text()
            assert f'name: "{display_name}"' in agents_md
            assert f'title: "{title}"' in agents_md
            assert f"I am the {title}." in agents_md
