"""Schema-backed file loaders for compiler entities."""

from __future__ import annotations

from pathlib import Path

from clawscaffold.models import ProfileSpec, ProposalEnvelope, TargetSpec, TenantSpec
from clawscaffold.validation import validate_yaml_file


def load_target_spec(path: str | Path) -> TargetSpec:
    data = validate_yaml_file(path, "target.schema.json")
    return TargetSpec.from_dict(data)


def load_profile_spec(path: str | Path) -> ProfileSpec:
    data = validate_yaml_file(path, "profile.schema.json")
    return ProfileSpec.from_dict(data)


def load_tenant_spec(path: str | Path) -> TenantSpec:
    data = validate_yaml_file(path, "tenant.schema.json")
    return TenantSpec.from_dict(data)


def load_proposal(path: str | Path) -> ProposalEnvelope:
    data = validate_yaml_file(path, "proposal.schema.json")
    return ProposalEnvelope.from_dict(data)
