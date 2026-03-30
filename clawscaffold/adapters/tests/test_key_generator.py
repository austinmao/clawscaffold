"""Tests for API key generation via generate_keys()."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from clawscaffold.adapters.cli_runner import KeyResult
from clawscaffold.adapters.hierarchy_reader import MergedAgent
from clawscaffold.adapters.key_generator import generate_keys


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


# ---------------------------------------------------------------------------
# Helpers to redirect KEY_STORAGE_DIR and MAIN_KEY_PATH to tmp_path
# ---------------------------------------------------------------------------


def _patch_paths(tmp_path: Path):
    """Return a context stack that redirects storage paths into tmp_path."""
    storage_dir = tmp_path / "keys"
    storage_dir.mkdir(parents=True, exist_ok=True)
    main_key = tmp_path / "paperclip-claimed-api-key.json"
    return storage_dir, main_key


class TestGenerateKeys:
    """Unit tests for generate_keys() with mocked subprocess via generate_agent_key."""

    def test_generates_keys_for_all_agents(self, tmp_path):
        """generate_agent_key is called for each agent; summary.generated matches."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="cmo",
                success=True,
                token="pcp_test123",
                agent_uuid="uuid-agent-1",
                company_uuid="comp-1",
            )

            agents = [_make_agent()]
            summary = generate_keys(agents, company_id="comp-1")

        assert summary.generated == 1
        assert summary.skipped == 0
        assert summary.failed == 0
        assert summary.errors == []
        mock_gen.assert_called_once_with("cmo", "comp-1", None)

    def test_generates_keys_for_multiple_agents(self, tmp_path):
        """Key file is written for each successfully generated agent."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.side_effect = [
                KeyResult(
                    key="cmo", success=True, token="tok1", agent_uuid="u1", company_uuid="c1"
                ),
                KeyResult(
                    key="copywriter", success=True, token="tok2", agent_uuid="u2", company_uuid="c1"
                ),
            ]

            agents = [
                _make_agent(key="cmo", id="executive/cmo", org_level="executive"),
                _make_agent(key="copywriter", id="content/copywriter", org_level="specialist"),
            ]
            summary = generate_keys(agents, company_id="c1")

        assert summary.generated == 2
        assert summary.skipped == 0
        assert summary.failed == 0
        assert (storage_dir / "cmo.json").is_file()
        assert (storage_dir / "copywriter.json").is_file()

    def test_key_file_content_is_correct(self, tmp_path):
        """Written key JSON contains token, agentId, companyId, and keyName."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="cmo",
                success=True,
                token="pcp_tok_abc",
                agent_uuid="agent-uuid-xyz",
                company_uuid="comp-uuid-123",
            )

            agents = [_make_agent()]
            generate_keys(agents, company_id="comp-uuid-123")

        key_data = json.loads((storage_dir / "cmo.json").read_text())
        assert key_data["token"] == "pcp_tok_abc"
        assert key_data["agentId"] == "agent-uuid-xyz"
        assert key_data["companyId"] == "comp-uuid-123"
        assert key_data["keyName"] == "local-cli"

    # ------------------------------------------------------------------
    # Idempotency: existing key file is skipped when force=False
    # ------------------------------------------------------------------

    def test_skips_existing_key_when_force_false(self, tmp_path):
        """Existing key file is not regenerated when force=False."""
        storage_dir, main_key = _patch_paths(tmp_path)
        existing = storage_dir / "cmo.json"
        existing.write_text(json.dumps({"token": "old_token"}))

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            agents = [_make_agent()]
            summary = generate_keys(agents, company_id="comp-1", force=False)

        assert summary.skipped == 1
        assert summary.generated == 0
        assert summary.failed == 0
        mock_gen.assert_not_called()
        # Original file is unchanged
        assert json.loads(existing.read_text())["token"] == "old_token"

    def test_skips_all_when_all_keys_exist(self, tmp_path):
        """All agents are skipped when every key file already exists."""
        storage_dir, main_key = _patch_paths(tmp_path)
        for key in ("cmo", "copywriter"):
            (storage_dir / f"{key}.json").write_text("{}")

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            agents = [
                _make_agent(key="cmo"),
                _make_agent(key="copywriter", id="content/copywriter"),
            ]
            summary = generate_keys(agents, company_id="comp-1", force=False)

        assert summary.skipped == 2
        assert summary.generated == 0
        mock_gen.assert_not_called()

    # ------------------------------------------------------------------
    # force=True regenerates even when key file exists
    # ------------------------------------------------------------------

    def test_force_regenerates_existing_key(self, tmp_path):
        """force=True overwrites the existing key file with a fresh value."""
        storage_dir, main_key = _patch_paths(tmp_path)
        key_file = storage_dir / "cmo.json"
        key_file.write_text(json.dumps({"token": "old_tok"}))

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="cmo",
                success=True,
                token="new_tok_force",
                agent_uuid="uuid-new",
                company_uuid="comp-1",
            )

            agents = [_make_agent()]
            summary = generate_keys(agents, company_id="comp-1", force=True)

        assert summary.generated == 1
        assert summary.skipped == 0
        mock_gen.assert_called_once()
        refreshed = json.loads(key_file.read_text())
        assert refreshed["token"] == "new_tok_force"

    def test_force_true_without_existing_file_generates(self, tmp_path):
        """force=True with no pre-existing file still generates the key."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="cmo",
                success=True,
                token="tok_fresh",
                agent_uuid="uuid-f",
                company_uuid="comp-1",
            )

            agents = [_make_agent()]
            summary = generate_keys(agents, company_id="comp-1", force=True)

        assert summary.generated == 1
        assert summary.skipped == 0

    # ------------------------------------------------------------------
    # Error handling: failures are logged but don't stop other agents
    # ------------------------------------------------------------------

    def test_failed_key_generation_logged_and_continues(self, tmp_path):
        """A failed agent is counted in failed; processing continues for next agents."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.side_effect = [
                KeyResult(key="cmo", success=False, error="connection refused"),
                KeyResult(
                    key="copywriter", success=True, token="tok2", agent_uuid="u2", company_uuid="c1"
                ),
            ]

            agents = [
                _make_agent(key="cmo", org_level="executive"),
                _make_agent(key="copywriter", id="content/copywriter", org_level="specialist"),
            ]
            summary = generate_keys(agents, company_id="c1")

        assert summary.failed == 1
        assert summary.generated == 1
        assert "cmo: connection refused" in summary.errors
        # Successful agent key file still written
        assert (storage_dir / "copywriter.json").is_file()
        assert not (storage_dir / "cmo.json").is_file()

    def test_all_failures_accumulate_errors(self, tmp_path):
        """Multiple failed agents each add an entry to summary.errors."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.side_effect = [
                KeyResult(key="cmo", success=False, error="timeout"),
                KeyResult(key="copywriter", success=False, error="not found"),
            ]

            agents = [
                _make_agent(key="cmo"),
                _make_agent(key="copywriter", id="content/copywriter"),
            ]
            summary = generate_keys(agents, company_id="c1")

        assert summary.failed == 2
        assert summary.generated == 0
        assert len(summary.errors) == 2
        assert "cmo: timeout" in summary.errors
        assert "copywriter: not found" in summary.errors

    # ------------------------------------------------------------------
    # C-suite key is copied to MAIN_KEY_PATH
    # ------------------------------------------------------------------

    def test_csuite_key_written_to_main_key_path(self, tmp_path):
        """First executive-level agent key is copied to paperclip-claimed-api-key.json."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="cmo",
                success=True,
                token="pcp_main_tok",
                agent_uuid="agent-exec-uuid",
                company_uuid="comp-xyz",
            )

            agents = [_make_agent(org_level="executive")]
            generate_keys(agents, company_id="comp-xyz")

        assert main_key.is_file()
        main_data = json.loads(main_key.read_text())
        assert main_data["token"] == "pcp_main_tok"
        assert main_data["agentId"] == "agent-exec-uuid"
        assert main_data["companyId"] == "comp-xyz"
        assert main_data["keyName"] == "local-cli"

    def test_director_key_also_qualifies_for_main_key(self, tmp_path):
        """A director-level agent is treated as C-suite and copied to MAIN_KEY_PATH."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="sales-director",
                success=True,
                token="tok_director",
                agent_uuid="dir-uuid",
                company_uuid="comp-1",
            )

            agents = [_make_agent(key="sales-director", id="sales/director", org_level="director")]
            generate_keys(agents, company_id="comp-1")

        assert main_key.is_file()
        assert json.loads(main_key.read_text())["token"] == "tok_director"

    def test_non_csuite_agent_does_not_write_main_key(self, tmp_path):
        """A specialist-level agent does NOT overwrite MAIN_KEY_PATH."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="copywriter",
                success=True,
                token="tok_writer",
                agent_uuid="w-uuid",
                company_uuid="comp-1",
            )

            agents = [
                _make_agent(key="copywriter", id="content/copywriter", org_level="specialist")
            ]
            generate_keys(agents, company_id="comp-1")

        assert not main_key.is_file()

    def test_first_csuite_wins_main_key(self, tmp_path):
        """When multiple C-suite agents exist, only the first one's key goes to MAIN_KEY_PATH."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.side_effect = [
                KeyResult(
                    key="cmo", success=True, token="tok_cmo", agent_uuid="u1", company_uuid="c1"
                ),
                KeyResult(
                    key="cto", success=True, token="tok_cto", agent_uuid="u2", company_uuid="c1"
                ),
            ]

            agents = [
                _make_agent(key="cmo", id="executive/cmo", org_level="executive"),
                _make_agent(key="cto", id="executive/cto", org_level="executive"),
            ]
            generate_keys(agents, company_id="c1")

        assert json.loads(main_key.read_text())["token"] == "tok_cmo"

    # ------------------------------------------------------------------
    # Paperclip dir is forwarded to generate_agent_key
    # ------------------------------------------------------------------

    def test_paperclip_dir_forwarded_to_cli(self, tmp_path):
        """paperclip_dir is passed through to generate_agent_key."""
        storage_dir, main_key = _patch_paths(tmp_path)
        pdir = tmp_path / "services" / "paperclip"
        pdir.mkdir(parents=True)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            mock_gen.return_value = KeyResult(
                key="cmo", success=True, token="tok", agent_uuid="u", company_uuid="c"
            )

            agents = [_make_agent()]
            generate_keys(agents, company_id="c", paperclip_dir=pdir)

        mock_gen.assert_called_once_with("cmo", "c", pdir)

    # ------------------------------------------------------------------
    # Empty input
    # ------------------------------------------------------------------

    def test_empty_agent_list_returns_empty_summary(self, tmp_path):
        """No agents → all counts are zero, no files written."""
        storage_dir, main_key = _patch_paths(tmp_path)

        with (
            patch("clawscaffold.adapters.key_generator.KEY_STORAGE_DIR", storage_dir),
            patch("clawscaffold.adapters.key_generator.MAIN_KEY_PATH", main_key),
            patch("clawscaffold.adapters.key_generator.generate_agent_key") as mock_gen,
        ):
            summary = generate_keys([], company_id="comp-1")

        assert summary.generated == 0
        assert summary.skipped == 0
        assert summary.failed == 0
        assert summary.errors == []
        mock_gen.assert_not_called()
        assert not main_key.is_file()
