"""Abstract MCP hook — MCP tool registration integration."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPHook:
    """No-op MCP hook. Override for MCP tool registration integration."""

    def register_tools(self, tools: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        logger.debug("MCPHook.register_tools called (no-op): %d tools", len(tools))
        return {"registered": False, "reason": "no MCP hook registered", "count": 0}
