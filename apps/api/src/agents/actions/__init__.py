"""Action implementations split out from the monolithic actions.py.

This package holds heavier actions (multi-step + side effects + GGUF
conversion subprocess) so the core ``automation_engine.actions`` module
stays focused on the small/declarative kinds.
"""
from __future__ import annotations

from .publish_adapter_to_ollama import PublishAdapterToOllama

__all__ = ["PublishAdapterToOllama"]
