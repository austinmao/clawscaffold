"""Tests for .paperclip.yaml generation from catalog specs."""

from __future__ import annotations

import os
from unittest.mock import patch

from clawscaffold.adapters.hierarchy_reader import MergedAgent
from clawscaffold.adapters.yaml_generator import generate_paperclip_yaml


def _make_agent(**overrides) -> MergedAgent:
    defaults = {
        "id": "executive/cmo",
        "key": "cmo",
        "gateway_agent_id": "agents-executive-cmo",
        "title": "Chief Marketing Officer",
        "display_name": "CMO",
        "description": "Orchestrates marketing operations",
        "emoji": "\U0001f3af",
        "role": "pm",
        "reports_to_key": None,
        "budget_monthly_cents": 5000,
        "heartbeat_enabled": False,
        "lifecycle_bridge": "not_enrolled",
        "timeout_sec": 60,
        "org_level": "executive",
        "manages": [],
    }
    defaults.update(overrides)
    return MergedAgent(**defaults)


class TestGeneratePaperclipYaml:
    def test_basic_structure(self):
        agents = [_make_agent()]
        result = generate_paperclip_yaml(agents)

        assert result["schema"] == "paperclip/v1"
        assert "agents" in result
        assert "sidebar" in result
        assert "cmo" in result["agents"]

    def test_agent_fields(self):
        agents = [_make_agent()]
        result = generate_paperclip_yaml(agents)
        cmo = result["agents"]["cmo"]

        assert cmo["role"] == "pm"
        assert cmo["capabilities"] == "Orchestrates marketing operations"
        assert cmo["icon"] == "\U0001f3af"
        assert cmo["budgetMonthlyCents"] == 5000

    def test_adapter_config(self):
        agents = [_make_agent()]
        with patch.dict(
            os.environ,
            {"OPENCLAW_GATEWAY_URL": "ws://test:18789", "OPENCLAW_GATEWAY_TOKEN": "tok_123"},
        ):
            result = generate_paperclip_yaml(agents)

        adapter = result["agents"]["cmo"]["adapter"]
        assert adapter["type"] == "openclaw_gateway"
        assert adapter["config"]["url"] == "ws://test:18789"
        assert adapter["config"]["authToken"] == "tok_123"
        assert adapter["config"]["sessionKeyStrategy"] == "run"

    def test_reports_to(self):
        agents = [
            _make_agent(),
            _make_agent(
                id="content/copywriter",
                key="copywriter",
                title="Copywriter",
                role="engineer",
                reports_to_key="cmo",
                org_level="specialist",
            ),
        ]
        result = generate_paperclip_yaml(agents)
        assert result["agents"]["copywriter"]["reportsTo"] == "cmo"
        assert "reportsTo" not in result["agents"]["cmo"]

    def test_heartbeat_config(self):
        agents = [_make_agent(heartbeat_enabled=True, lifecycle_bridge="supported")]
        result = generate_paperclip_yaml(agents)

        runtime = result["agents"]["cmo"]["runtime"]
        assert runtime["heartbeat"]["enabled"] is True
        assert runtime["heartbeat"]["wakeOnDemand"] is True

    def test_sidebar_order(self):
        agents = [
            _make_agent(key="cmo"),
            _make_agent(key="copywriter", id="content/copywriter"),
            _make_agent(key="nova", id="engineering/frontend-engineer"),
        ]
        result = generate_paperclip_yaml(agents)
        assert result["sidebar"]["agents"] == ["cmo", "copywriter", "nova"]

    def test_no_auth_token(self):
        agents = [_make_agent()]
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing token
            env = {k: v for k, v in os.environ.items() if k != "OPENCLAW_GATEWAY_TOKEN"}
            with patch.dict(os.environ, env, clear=True):
                result = generate_paperclip_yaml(agents)

        assert "authToken" not in result["agents"]["cmo"]["adapter"]["config"]

    def test_custom_timeout(self):
        agents = [_make_agent(timeout_sec=120)]
        result = generate_paperclip_yaml(agents)
        assert result["agents"]["cmo"]["adapter"]["config"]["timeoutSec"] == 120

    def test_empty_agents(self):
        result = generate_paperclip_yaml([])
        assert result["agents"] == {}
        assert result["sidebar"]["agents"] == []

    def test_three_level_agents_structure(self):
        """Executive, engineer (lead), and specialist agents all produce valid entries."""
        executive = _make_agent(
            id="executive/cmo",
            key="cmo",
            title="Chief Marketing Officer",
            display_name="CMO",
            role="pm",
            org_level="executive",
            reports_to_key=None,
            budget_monthly_cents=10000,
            emoji="\U0001f3af",
        )
        engineer = _make_agent(
            id="engineering/frontend-engineer",
            key="frontend-engineer",
            title="Frontend Engineer",
            display_name="Nova",
            role="engineer",
            org_level="lead",
            reports_to_key="cmo",
            budget_monthly_cents=3000,
            emoji="\u2728",
        )
        specialist = _make_agent(
            id="content/copywriter",
            key="copywriter",
            title="Copywriter",
            display_name="Quill",
            role="engineer",
            org_level="specialist",
            reports_to_key="cmo",
            budget_monthly_cents=1500,
            emoji="\u270f\ufe0f",
        )
        result = generate_paperclip_yaml([executive, engineer, specialist])

        assert "cmo" in result["agents"]
        assert "frontend-engineer" in result["agents"]
        assert "copywriter" in result["agents"]

        # Executive has pm role; others have engineer role
        assert result["agents"]["cmo"]["role"] == "pm"
        assert result["agents"]["frontend-engineer"]["role"] == "engineer"
        assert result["agents"]["copywriter"]["role"] == "engineer"

        # budgetMonthlyCents propagated for each level
        assert result["agents"]["cmo"]["budgetMonthlyCents"] == 10000
        assert result["agents"]["frontend-engineer"]["budgetMonthlyCents"] == 3000
        assert result["agents"]["copywriter"]["budgetMonthlyCents"] == 1500

        # reportsTo resolved to short key for non-executive agents
        assert "reportsTo" not in result["agents"]["cmo"]
        assert result["agents"]["frontend-engineer"]["reportsTo"] == "cmo"
        assert result["agents"]["copywriter"]["reportsTo"] == "cmo"

        # icon/emoji mapping present for all three
        assert result["agents"]["cmo"]["icon"] == "\U0001f3af"
        assert result["agents"]["frontend-engineer"]["icon"] == "\u2728"
        assert result["agents"]["copywriter"]["icon"] == "\u270f\ufe0f"

    def test_sidebar_ordered_by_org_level_then_alphabetical(self):
        """Sidebar agents list preserves insertion order (caller is responsible for sorting)."""
        # generate_paperclip_yaml preserves the order agents are passed in.
        # merge_agents() (the caller) sorts by org_level then alphabetical.
        # We simulate that pre-sorted input here and confirm order is preserved.
        executive = _make_agent(key="cmo", id="executive/cmo", org_level="executive")
        lead_alpha = _make_agent(key="atlas", id="marketing/atlas", org_level="lead")
        lead_beta = _make_agent(key="nova", id="engineering/nova", org_level="lead")
        specialist = _make_agent(key="copywriter", id="content/copywriter", org_level="specialist")

        result = generate_paperclip_yaml([executive, lead_alpha, lead_beta, specialist])
        assert result["sidebar"]["agents"] == ["cmo", "atlas", "nova", "copywriter"]

    def test_auth_token_injected_via_monkeypatch(self, monkeypatch):
        """authToken env var is injected into every agent's adapter config."""
        monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "test-token-abc")
        monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "ws://localhost:18789")

        agents = [_make_agent()]
        result = generate_paperclip_yaml(agents)

        adapter_config = result["agents"]["cmo"]["adapter"]["config"]
        assert adapter_config["authToken"] == "test-token-abc"
        assert result["agents"]["cmo"]["adapter"]["type"] == "openclaw_gateway"
        assert adapter_config["sessionKeyStrategy"] == "run"

    def test_missing_auth_token_omits_field(self, monkeypatch):
        """When OPENCLAW_GATEWAY_TOKEN is absent, authToken key must not appear."""
        monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)

        agents = [_make_agent()]
        result = generate_paperclip_yaml(agents)

        assert "authToken" not in result["agents"]["cmo"]["adapter"]["config"]

    def test_no_emoji_omits_icon(self):
        """Agents without an emoji must not have an icon key in the output."""
        agents = [_make_agent(emoji="")]
        result = generate_paperclip_yaml(agents)
        assert "icon" not in result["agents"]["cmo"]

    def test_zero_budget_omits_field(self):
        """Zero budgetMonthlyCents should not appear in the output entry."""
        agents = [_make_agent(budget_monthly_cents=0)]
        result = generate_paperclip_yaml(agents)
        assert "budgetMonthlyCents" not in result["agents"]["cmo"]
