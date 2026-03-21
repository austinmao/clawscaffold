"""Proposal envelope helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawscaffold.models import ProposalEnvelope
from clawscaffold.utils import now_iso, write_json
from clawscaffold.utils import run_id as generate_run_id
from clawscaffold.validation import validate_dict


def create_proposal(
    action: str,
    target_id: str,
    proposer: str,
    payload: dict[str, Any],
    tenant: str = "default",
    parent_run_id: str | None = None,
) -> ProposalEnvelope:
    envelope = ProposalEnvelope(
        action=action,
        run_id=generate_run_id(action),
        proposer=proposer,
        tenant=tenant,
        created_at=now_iso(),
        state="proposed",
        payload=payload,
        parent_run_id=parent_run_id,
    )
    validate_dict(envelope.to_dict(), "proposal.schema.json")
    return envelope


def write_proposal(proposal: ProposalEnvelope, run_dir: Path) -> Path:
    path = run_dir / "proposal.json"
    write_json(path, proposal.to_dict())
    return path


def create_amendment(
    parent_run_id: str,
    reason: str,
    changes: list[dict[str, Any]],
    target_id: str,
    proposer: str = "human:scaffold-cli",
    tenant: str = "default",
) -> ProposalEnvelope:
    return create_proposal(
        action="amend",
        target_id=target_id,
        proposer=proposer,
        tenant=tenant,
        parent_run_id=parent_run_id,
        payload={
            "target_run_id": parent_run_id,
            "reason": reason,
            "changes": changes,
        },
    )
