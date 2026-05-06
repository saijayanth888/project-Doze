"""Trigger types — describe what causes a workflow to run.

The runtime side of triggers (registering crons with APScheduler, subscribing
to the event bus, mounting webhook routes) lives in :mod:`engine`. This file
just owns the type catalog that the UI form builder consumes via
``GET /api/automation/triggers/schema``.
"""

from __future__ import annotations

from typing import Any

# Common evolution events publishers should emit. Keep in sync with whatever
# `runner.py` and `evolution_graph.py` actually publish so the UI can offer
# concrete dropdown options instead of a text field.
KNOWN_EVENTS: list[dict[str, str]] = [
    {"key": "evolution.started",       "label": "Evolution started"},
    {"key": "evolution.completed",     "label": "Evolution completed"},
    {"key": "evolution.failed",        "label": "Evolution failed"},
    {"key": "generation.completed",    "label": "Generation completed"},
    {"key": "generation.discarded",    "label": "Generation discarded"},
    {"key": "champion.promoted",       "label": "Champion promoted"},
    {"key": "champion.regressed",      "label": "Champion regressed"},
    {"key": "drift.detected",          "label": "Drift detected"},
    {"key": "ept.started",             "label": "EPT run started"},
    {"key": "ept.completed",           "label": "EPT run completed"},
    {"key": "health.degraded",         "label": "Service health degraded"},
]

CRON_PRESETS: list[dict[str, str]] = [
    {"label": "Every 15 minutes", "cron": "*/15 * * * *"},
    {"label": "Every hour",        "cron": "0 * * * *"},
    {"label": "Every 6 hours",     "cron": "0 */6 * * *"},
    {"label": "Daily at 02:00",    "cron": "0 2 * * *"},
    {"label": "Daily at 08:00",    "cron": "0 8 * * *"},
    {"label": "Weekday at 09:00",  "cron": "0 9 * * 1-5"},
    {"label": "Sunday at 09:00",   "cron": "0 9 * * 0"},
    {"label": "Sunday at 03:00",   "cron": "0 3 * * 0"},
]


TRIGGER_TYPES: list[dict[str, Any]] = [
    {
        "kind": "cron",
        "label": "On a schedule",
        "description": "Run on a cron schedule.",
        "schema": [
            {"name": "cron", "type": "string", "label": "Cron expression",
             "required": True, "default": "0 2 * * *",
             "help": "Standard 5-field cron. See presets for common cadences."},
        ],
        "presets": CRON_PRESETS,
    },
    {
        "kind": "event",
        "label": "When an event happens",
        "description": "Run when a domain event matches the pattern (e.g. champion.promoted).",
        "schema": [
            {"name": "pattern", "type": "string", "label": "Event pattern",
             "required": True, "default": "champion.promoted",
             "help": "Use shell-style wildcards: 'evolution.*' matches all evolution.* topics."},
        ],
        "events": KNOWN_EVENTS,
    },
    {
        "kind": "webhook",
        "label": "On a webhook",
        "description": "Expose a POST endpoint that fires the workflow with the request body.",
        "schema": [],
    },
    {
        "kind": "manual",
        "label": "Manual only",
        "description": "Never fires automatically; only via the 'Run now' button.",
        "schema": [],
    },
]


def trigger_schemas() -> list[dict[str, Any]]:
    return TRIGGER_TYPES


__all__ = ["TRIGGER_TYPES", "KNOWN_EVENTS", "CRON_PRESETS", "trigger_schemas"]
