"""Backwards-compat shim — automation engine moved to ``services.automation_engine``.

Existing imports like ``from services.automation import get_engine`` continue
to work. New code should prefer importing from ``services.automation_engine``.
"""

from __future__ import annotations

from services.automation_engine import (  # noqa: F401
    ACTION_REGISTRY,
    AutomationEngine,
    DEFAULT_JOBS,
    TRIGGER_TYPES,
    action_schemas,
    attach_engine,
    get_engine,
    trigger_schemas,
)

__all__ = [
    "ACTION_REGISTRY",
    "AutomationEngine",
    "DEFAULT_JOBS",
    "TRIGGER_TYPES",
    "action_schemas",
    "attach_engine",
    "get_engine",
    "trigger_schemas",
]
