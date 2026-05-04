"""Abstract governance hook — issue-tracker integration."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GovernanceHook:
    """No-op governance hook. Override for issue-tracker integration."""

    def sync_target(self, target_id: str, **kwargs: Any) -> dict[str, Any]:
        logger.debug("GovernanceHook.sync_target called (no-op): %s", target_id)
        return {"synced": False, "reason": "no governance hook registered"}

    def export_issues(self, **kwargs: Any) -> list[dict[str, Any]]:
        logger.debug("GovernanceHook.export_issues called (no-op)")
        return []
