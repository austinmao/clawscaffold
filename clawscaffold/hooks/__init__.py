"""Abstract hook interfaces for optional integrations."""

from clawscaffold.hooks.governance import GovernanceHook
from clawscaffold.hooks.mcp import MCPHook
from clawscaffold.hooks.outbound import OutboundHook

__all__ = ["GovernanceHook", "OutboundHook", "MCPHook"]
