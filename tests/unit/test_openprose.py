"""Tests for the OpenProse adapter."""

from __future__ import annotations

from clawscaffold.scaffold.adapters.openprose import generate_prose


def test_generate_prose_keeps_distinct_agent_labels_unique():
    prose = generate_prose(
        [
            {
                "id": "frontend",
                "agent": "agents-website-frontend-engineer",
                "task": "Build the website preview",
                "parallel": True,
            },
            {
                "id": "email",
                "agent": "agents-marketing-email-engineer",
                "task": "Build the email preview",
                "parallel": True,
            },
        ],
        "lumina-demo",
    )

    assert "agent website_frontend_engineer:" in prose
    assert "agent marketing_email_engineer:" in prose
    assert "agent engineer:" not in prose
    assert "frontend = session: website_frontend_engineer" in prose
    assert "email = session: marketing_email_engineer" in prose
