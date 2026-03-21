"""Control-plane merge rules for builder outputs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

DOMAIN_OWNERSHIP = {
    "target": "agent-architect",
    "skill": "skill-architect",
    "profile": "profile-architect",
    "docs": "docs-regenerator",
    "qa": "qa-architect",
    "model_policy": "model-policy-architect",
}


def merge_builder_outputs(outputs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {"domains": {}, "conflicts": [], "resolution_requests": []}
    for output in outputs:
        domain = output["domain"]
        owner = output["owner"]
        payload = output["payload"]
        expected_owner = DOMAIN_OWNERSHIP.get(domain)
        existing = merged["domains"].get(domain)
        if expected_owner and owner != expected_owner:
            merged["conflicts"].append({"domain": domain, "reason": "owner_mismatch", "owner": owner})
            merged["resolution_requests"].append(
                {"domain": domain, "required_owner": expected_owner, "provided_owner": owner}
            )
            continue
        if existing and existing != payload:
            merged["conflicts"].append({"domain": domain, "reason": "payload_conflict"})
            merged["resolution_requests"].append({"domain": domain, "reason": "payload_conflict"})
            continue
        merged["domains"][domain] = payload
    return merged
