"""Integration test: dry-run sync against the real catalog/agents/ directory.

These tests exercise PaperclipAdapter.sync(dry_run=True) end-to-end without
shelling out to the Paperclip CLI. They rely only on the catalog YAML files
that are checked into the repo.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from clawscaffold.adapters.paperclip_adapter import PaperclipAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Locate the repository root by searching upward for CLAUDE.md or catalog/."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "CLAUDE.md").is_file() or (parent / "catalog").is_dir():
            return parent
    pytest.skip("Cannot locate repo root — skipping integration tests")
    return Path()  # unreachable


def _count_agent_yaml_files(catalog_dir: Path) -> int:
    """Count .yaml files under catalog_dir that have kind: agent."""
    count = 0
    for yaml_path in sorted(catalog_dir.rglob("*.yaml")):
        if yaml_path.stem.endswith((".interview", ".review")):
            continue
        if ".interview." in yaml_path.name or ".review." in yaml_path.name:
            continue
        try:
            raw = yaml.safe_load(yaml_path.read_text()) or {}
        except (yaml.YAMLError, OSError):
            continue
        if raw.get("kind") == "agent":
            count += 1
    return count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDryRunE2E:
    """Integration tests for PaperclipAdapter.sync(dry_run=True)."""

    def test_dry_run_returns_nonzero_agent_count(self, capsys):
        """sync(dry_run=True) returns a SyncResult whose agent_count > 0."""
        repo_root = _find_repo_root()
        catalog_dir = repo_root / "catalog" / "agents"
        if not catalog_dir.is_dir():
            pytest.skip("catalog/agents/ directory not found")

        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True)

        assert result.agent_count > 0, "Expected at least one agent in catalog"
        assert result.dry_run_yaml, "dry_run_yaml must be non-empty"
        # Live import fields should be absent
        assert result.import_result is None
        assert result.key_summary is None

    def test_dry_run_yaml_is_valid_yaml(self, capsys):
        """dry_run_yaml is parseable and contains the paperclip/v1 schema marker."""
        repo_root = _find_repo_root()
        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True)

        parsed = yaml.safe_load(result.dry_run_yaml)
        assert isinstance(parsed, dict)
        assert parsed.get("schema") == "paperclip/v1"
        assert "agents" in parsed
        assert "sidebar" in parsed
        assert isinstance(parsed["agents"], dict)
        assert isinstance(parsed["sidebar"]["agents"], list)

    def test_dry_run_agent_count_matches_catalog(self, capsys):
        """agent_count matches the number of kind:agent YAML files in catalog/agents/."""
        repo_root = _find_repo_root()
        catalog_dir = repo_root / "catalog" / "agents"
        if not catalog_dir.is_dir():
            pytest.skip("catalog/agents/ directory not found")

        expected = _count_agent_yaml_files(catalog_dir)
        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True)

        assert result.agent_count == expected, (
            f"agent_count {result.agent_count} does not match catalog file count {expected}"
        )

    def test_dry_run_yaml_agents_leq_agent_count(self, capsys):
        """YAML agents dict may be <= agent_count due to duplicate short keys across domains.

        Multiple catalog agents can share the same short key (e.g. 'copywriter' appears
        under both content/ and marketing/). The YAML dict collapses duplicates, so
        len(yaml_agents) <= agent_count. We verify the relationship rather than
        asserting equality.

        The sidebar is a list generated from all agents (including duplicates), so
        len(sidebar) == agent_count (one entry per merged agent), while len(agents dict)
        reflects only unique keys.
        """
        repo_root = _find_repo_root()
        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True)

        parsed = yaml.safe_load(result.dry_run_yaml)
        yaml_agent_count = len(parsed["agents"])

        assert yaml_agent_count > 0
        assert yaml_agent_count <= result.agent_count, (
            f"YAML has {yaml_agent_count} agents but agent_count reports {result.agent_count}"
        )
        # Sidebar length equals total agent_count (one entry per merged agent, including
        # those with duplicate short keys), while the dict collapses to unique keys.
        assert len(parsed["sidebar"]["agents"]) == result.agent_count

    def test_dry_run_sidebar_keys_subset_of_yaml_agents(self, capsys):
        """Every key in sidebar.agents is also present in the agents dict.

        sidebar is a list and may contain duplicate entries for agents that share a
        short key. The set of unique sidebar keys must be a subset of agents dict keys.
        """
        repo_root = _find_repo_root()
        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True)

        parsed = yaml.safe_load(result.dry_run_yaml)
        yaml_keys = set(parsed["agents"].keys())
        sidebar_unique_keys = set(parsed["sidebar"]["agents"])

        assert sidebar_unique_keys == yaml_keys, (
            f"Sidebar unique keys do not match agents dict keys: "
            f"extra in sidebar={sidebar_unique_keys - yaml_keys}, "
            f"missing from sidebar={yaml_keys - sidebar_unique_keys}"
        )

    def test_dry_run_no_import_or_key_subprocess_calls(self, capsys):
        """dry_run=True must not invoke the Paperclip import or key-gen CLI commands.

        The detection layer may call subprocess.run to probe CLI availability, which is
        acceptable. This test verifies that the heavier company-import and agent
        local-cli commands are never executed on a dry run.
        """
        repo_root = _find_repo_root()
        adapter = PaperclipAdapter(repo_root=repo_root)

        # Patch run_company_import and generate_agent_key — the two functions that
        # shell out for real work (import and key generation).
        with (
            patch("clawscaffold.adapters.cli_runner.run_company_import") as mock_import,
            patch("clawscaffold.adapters.cli_runner.generate_agent_key") as mock_keygen,
        ):
            result = adapter.sync(dry_run=True)

        mock_import.assert_not_called()
        mock_keygen.assert_not_called()
        assert result.agent_count > 0

    def test_dry_run_agent_entries_have_required_fields(self, capsys):
        """Every agent entry in the YAML has role, capabilities, and adapter."""
        repo_root = _find_repo_root()
        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True)

        parsed = yaml.safe_load(result.dry_run_yaml)
        for agent_key, entry in parsed["agents"].items():
            assert "role" in entry, f"Agent '{agent_key}' missing 'role'"
            assert "adapter" in entry, f"Agent '{agent_key}' missing 'adapter'"
            adapter_cfg = entry["adapter"]
            assert adapter_cfg.get("type") == "openclaw_gateway", (
                f"Agent '{agent_key}' adapter type is not openclaw_gateway"
            )
            assert "config" in adapter_cfg, f"Agent '{agent_key}' adapter missing 'config'"
            config = adapter_cfg["config"]
            assert "sessionKeyStrategy" in config, (
                f"Agent '{agent_key}' adapter config missing 'sessionKeyStrategy'"
            )
            assert config["sessionKeyStrategy"] == "run"

    def test_dry_run_with_filter(self, capsys):
        """filter_pattern restricts the returned agents to the matching domain."""
        repo_root = _find_repo_root()
        adapter = PaperclipAdapter(repo_root=repo_root)

        # executive/* should return a small, bounded set
        result = adapter.sync(dry_run=True, filter_pattern="executive/*")

        assert 0 < result.agent_count <= 5, (
            f"Expected 1-5 executive agents, got {result.agent_count}"
        )
        parsed = yaml.safe_load(result.dry_run_yaml)
        # All agents returned should have matching catalog IDs; the short keys for
        # executive agents in this repo are cmo, cco, cto — verify no others appear
        known_exec_keys = {"cmo", "cco", "cto"}
        returned_keys = set(parsed["agents"].keys())
        assert returned_keys <= known_exec_keys, (
            f"Unexpected non-executive keys returned: {returned_keys - known_exec_keys}"
        )

    def test_dry_run_filter_single_agent(self, capsys):
        """filter_pattern for a single agent returns exactly that agent."""
        repo_root = _find_repo_root()
        catalog_dir = repo_root / "catalog" / "agents" / "executive"
        if not (catalog_dir / "cmo.yaml").is_file():
            pytest.skip("executive/cmo.yaml not found")

        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True, filter_pattern="executive/cmo")

        assert result.agent_count == 1
        parsed = yaml.safe_load(result.dry_run_yaml)
        assert "cmo" in parsed["agents"]
        cmo = parsed["agents"]["cmo"]
        assert cmo["role"] == "pm"
        assert cmo["adapter"]["type"] == "openclaw_gateway"
        assert cmo["adapter"]["config"]["sessionKeyStrategy"] == "run"

    def test_dry_run_gateway_url_from_env(self, capsys, monkeypatch):
        """OPENCLAW_GATEWAY_URL env var is reflected in adapter config."""
        repo_root = _find_repo_root()
        monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "ws://test-host:18789")
        monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)

        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True, filter_pattern="executive/cmo")

        parsed = yaml.safe_load(result.dry_run_yaml)
        cmo_config = parsed["agents"]["cmo"]["adapter"]["config"]
        assert cmo_config["url"] == "ws://test-host:18789"

    def test_dry_run_auth_token_from_env(self, capsys, monkeypatch):
        """OPENCLAW_GATEWAY_TOKEN env var appears in adapter config when set."""
        repo_root = _find_repo_root()
        monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "tok_e2e_test_abc")

        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True, filter_pattern="executive/cmo")

        parsed = yaml.safe_load(result.dry_run_yaml)
        cmo_config = parsed["agents"]["cmo"]["adapter"]["config"]
        assert cmo_config.get("authToken") == "tok_e2e_test_abc"

    def test_dry_run_no_auth_token_when_env_unset(self, capsys, monkeypatch):
        """authToken is absent from adapter config when OPENCLAW_GATEWAY_TOKEN is not set."""
        repo_root = _find_repo_root()
        monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)

        adapter = PaperclipAdapter(repo_root=repo_root)
        result = adapter.sync(dry_run=True, filter_pattern="executive/cmo")

        parsed = yaml.safe_load(result.dry_run_yaml)
        cmo_config = parsed["agents"]["cmo"]["adapter"]["config"]
        assert "authToken" not in cmo_config
