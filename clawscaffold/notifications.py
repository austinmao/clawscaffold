"""Channel-agnostic notification helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from clawscaffold.config_apply import run_openclaw_cmd
from clawscaffold.models import CLIResult, NotificationEvent, TenantSpec
from clawscaffold.utils import today_iso


def classify_notification_tier(run_result: dict) -> str:
    action = run_result.get("action", "")
    state = run_result.get("state", "")
    if action == "rollback" or state in {"rollback_pending", "rolled_back"}:
        return "priority_notify"
    if run_result.get("warnings") or state == "blocked":
        return "summary_notify"
    return "log_only"


def log_notification(event: NotificationEvent, root: Path | None = None) -> Path:
    repo = root or Path.cwd()
    log_path = repo / "memory" / "logs" / "scaffold" / f"{today_iso()}-notifications.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{event.tier}] {event.run_id}: {event.message}\n")
    return log_path


def deliver_notification(
    event: NotificationEvent,
    tenant: TenantSpec,
    runner: Callable[[list[str]], CLIResult] = run_openclaw_cmd,
) -> dict:
    log_path = log_notification(event)
    if not tenant.notifications:
        return {"delivered": 0, "logged": str(log_path)}
    if __import__("os").environ.get("SCAFFOLD_ENABLE_NOTIFICATIONS") != "1":
        return {"delivered": 0, "logged": str(log_path)}
    delivered = 0
    channels = tenant.notifications.get("channels", [])
    for channel in channels:
        if channel.get("significance") != event.tier:
            continue
        target = channel.get("target") or tenant.operator.get("contact")
        if not target:
            continue
        runner(
            [
                "message",
                "send",
                "--channel",
                channel["channel"],
                "--target",
                target,
                "--message",
                event.message,
            ]
        )
        delivered += 1
    return {"delivered": delivered, "logged": str(log_path)}
