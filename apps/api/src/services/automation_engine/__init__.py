"""ModelForge automation engine — workflows over triggers + conditions + actions.

Public surface (re-exported below):

* ``AutomationEngine`` / ``get_engine`` / ``attach_engine`` — process-wide singleton
* ``DEFAULT_JOBS`` — kept for backwards compatibility with the legacy /api/automation/jobs
  endpoint; the real workflow seeds live in :mod:`seeds`.
* ``ACTION_REGISTRY`` / ``TRIGGER_TYPES`` — for /api/automation routes that expose
  the schema to the UI's form builder.

The legacy module ``services.automation`` is now a thin shim that re-exports
from this package, so ``from services.automation import get_engine`` still works.
"""

from __future__ import annotations

from .actions import ACTION_REGISTRY, ActionResult, action_schemas
from .engine import (
    DEFAULT_JOBS,
    AutomationEngine,
    attach_engine,
    get_engine,
)
from .triggers import TRIGGER_TYPES, trigger_schemas

__all__ = [
    "ACTION_REGISTRY",
    "ActionResult",
    "AutomationEngine",
    "DEFAULT_JOBS",
    "TRIGGER_TYPES",
    "action_schemas",
    "attach_engine",
    "get_engine",
    "trigger_schemas",
]
