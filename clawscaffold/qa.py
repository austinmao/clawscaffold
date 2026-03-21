"""QA artifact generation."""

from __future__ import annotations

from pathlib import Path

from clawscaffold.clawspec_detect import detect_target_tier
from clawscaffold.clawspec_gen import generate_scenarios
from clawscaffold.models import ResolvedManifest
from clawscaffold.utils import write_yaml


def render_qa_outputs(resolved: ResolvedManifest, root: Path | None = None) -> Path:
    qa_policy = resolved.resolved.get("policy", {}).get("qa", {})
    clawspec_policy = qa_policy.get("clawspec", {}) if isinstance(qa_policy, dict) else {}
    base = root or Path.cwd()
    output_dir = base / "compiler" / "generated" / "qa" / resolved.target_id
    path = output_dir / "scenarios.yaml"
    if clawspec_policy.get("generate", True):
        tier = detect_target_tier(resolved.kind, resolved.target_id, resolved.resolved, base)
        scenarios = generate_scenarios(
            resolved.target_id,
            resolved.kind,
            resolved.resolved,
            tier,
            root=base,
        )
        if scenarios is not None:
            write_yaml(path, scenarios)
            return path

    categories = resolved.resolved.get("policy", {}).get("qa", {}).get("categories", {})
    scenarios = [
        {
            "id": "smoke-basic",
            "description": f"Smoke test for {resolved.target_id}",
            "required": True,
            "inputs": {"target_id": resolved.target_id},
            "expected": {"rendered": True},
        }
    ]
    if categories.get("security"):
        scenarios.append(
            {
                "id": "security-guardrails",
                "description": "Security guardrails remain enabled",
                "required": True,
                "expected": {"prompt_injection_guard": True},
            }
        )
    if categories.get("integration"):
        scenarios.append(
            {
                "id": "integration-routing",
                "description": "Integration wiring resolves correctly",
                "required": False,
                "expected": {"integrations_present": True},
            }
        )
    write_yaml(path, {"target_id": resolved.target_id, "scenarios": scenarios})
    return path


def check_runner_configured(tenant: dict[str, object] | object) -> bool:
    raw = tenant if isinstance(tenant, dict) else getattr(tenant, "raw", {})
    qa_config = raw.get("qa", {}) if isinstance(raw, dict) else {}
    runner = qa_config.get("runner", {})
    return bool(runner.get("command"))
