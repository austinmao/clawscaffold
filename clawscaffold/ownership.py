"""Config ownership and collision handling."""

from __future__ import annotations

from typing import Any

from clawscaffold.models import ConfigCollision


def resolve_config_collision(key: str, desired_value: Any, live_value: Any, mode: str) -> ConfigCollision:
    if live_value is None:
        return ConfigCollision(key, desired_value, live_value, mode, "compiler_owned")
    if desired_value == live_value:
        return ConfigCollision(key, desired_value, live_value, mode, "no_change")
    if mode == "keep_live":
        return ConfigCollision(key, desired_value, live_value, mode, "observed_not_owned")
    if mode == "adopt_desired":
        return ConfigCollision(key, desired_value, live_value, mode, "compiler_owned")
    if mode == "defer":
        return ConfigCollision(key, desired_value, live_value, mode, "deferred")
    if mode == "custom":
        return ConfigCollision(key, desired_value, live_value, mode, "custom_resolution")
    raise ValueError(f"Unsupported config collision mode: {mode}")


def build_collision_report(
    desired: dict[str, Any],
    live: dict[str, Any],
    policy: dict[str, Any],
) -> list[ConfigCollision]:
    mode = policy.get("collision_mode", "defer")
    report = []
    for key, value in desired.items():
        report.append(resolve_config_collision(key, value, live.get(key), mode))
    return report


def build_config_ops(desired: dict[str, Any], live: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for collision in build_collision_report(desired, live, policy):
        if collision.resolution == "compiler_owned":
            ops.append(
                {
                    "action": "set",
                    "key": collision.key,
                    "value": collision.desired_value,
                    "previous_value": collision.live_value,
                }
            )
    return ops
