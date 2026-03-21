"""Abstract outbound hook — ClawWrap target sync integration."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OutboundHook:
    """No-op outbound hook. Override for ClawWrap integration."""

    def sync_targets(self, targets: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        logger.debug("OutboundHook.sync_targets called (no-op): %d targets", len(targets))
        return {"synced": False, "reason": "no outbound hook registered", "count": 0}

    def generate_placeholders(self, spec: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        logger.debug("OutboundHook.generate_placeholders called (no-op)")
        return {}

    def write_placeholders(self, placeholders: dict[str, Any], **kwargs: Any) -> None:
        logger.debug("OutboundHook.write_placeholders called (no-op)")
