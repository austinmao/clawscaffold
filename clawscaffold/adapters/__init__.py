"""Adapters for syncing clawscaffold agents to external systems."""

from __future__ import annotations

from .cli_runner import ImportResult
from .detection import PaperclipEnvironment, detect_paperclip
from .key_generator import KeyGenSummary
from .paperclip_adapter import PaperclipAdapter, SyncResult

__all__ = [
    "ImportResult",
    "KeyGenSummary",
    "PaperclipAdapter",
    "PaperclipEnvironment",
    "SyncResult",
    "detect_paperclip",
]
