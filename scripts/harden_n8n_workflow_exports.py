#!/usr/bin/env python3
"""Strip instance-specific n8n export noise and apply production-oriented defaults.

Run from repo root after editing workflows in the UI and re-exporting::

    python3 scripts/harden_n8n_workflow_exports.py

Idempotent: safe to run multiple times.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / "integrations" / "n8n" / "workflows"

STRIP_TOP = frozenset(
    {
        "createdAt",
        "updatedAt",
        "id",
        "versionId",
        "shared",
        "tags",
        "scopes",
        "parentFolder",
        "pinData",
        "triggerCount",
        "meta",
    }
)

DESCRIPTIONS: dict[str, str] = {
    "Evolution Monitor": (
        "Production webhook for ModelForge evolution events (POST /webhook/evolution-events). "
        "Optional Slack via SLACK_WEBHOOK_URL. CORS allows http://api:8000 only (Docker API → n8n)."
    ),
    "Evolution Scheduler": (
        "Runs every 6h: GET evolve status and GPU; POST /api/evolve/start when idle and GPU is available. "
        "Uses MODELFORGE_API_KEY and EVOLUTION_* env on the n8n container."
    ),
    "Health Check Monitor": (
        "Every 15m: GET /api/system/health; on success posts heartbeat to /api/system/alerts; "
        "on failure notifies Slack (SLACK_WEBHOOK_URL) and API."
    ),
    "Error handler": (
        "Assign as n8n global error workflow (Settings). Posts workflow_error alerts to /api/system/alerts "
        "with MODELFORGE_API_KEY."
    ),
}


def _strip_export_noise(data: dict) -> None:
    for k in STRIP_TOP:
        data.pop(k, None)


def _set_description(data: dict) -> None:
    name = data.get("name")
    if isinstance(name, str) and name in DESCRIPTIONS:
        data["description"] = DESCRIPTIONS[name]


def _harden_evolution_monitor(data: dict) -> None:
    if data.get("name") != "Evolution Monitor":
        return
    settings = data.setdefault("settings", {})
    if isinstance(settings, dict):
        settings.setdefault("executionOrder", "v1")
        settings["saveManualExecutions"] = False
        settings.setdefault("callerPolicy", "workflowsFromSameOwner")
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("name") == "Evolution Event Webhook" and node.get("type") == "n8n-nodes-base.webhook":
            params = node.setdefault("parameters", {})
            opts = params.setdefault("options", {})
            if isinstance(opts, dict):
                # Tight CORS: FastAPI httpx typically sends no Origin; n8n allows non-browser POSTs.
                opts.setdefault("allowedOrigins", "http://api:8000")
            break


def _harden_evolution_scheduler(data: dict) -> None:
    if data.get("name") != "Evolution Scheduler":
        return
    settings = data.setdefault("settings", {})
    if isinstance(settings, dict):
        settings.setdefault("executionOrder", "v1")
        settings["saveManualExecutions"] = False
        settings.setdefault("callerPolicy", "workflowsFromSameOwner")
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        name = node.get("name")
        if node.get("type") != "n8n-nodes-base.httpRequest":
            continue
        params = node.setdefault("parameters", {})
        opts = params.setdefault("options", {})
        if not isinstance(opts, dict):
            continue
        if name == "GET GPU Status" and "timeout" not in opts:
            opts["timeout"] = 20000
        if name == "POST Start Evolution" and "timeout" not in opts:
            opts["timeout"] = 120000


def _harden_health(data: dict) -> None:
    if data.get("name") != "Health Check Monitor":
        return
    settings = data.setdefault("settings", {})
    if isinstance(settings, dict):
        settings.setdefault("executionOrder", "v1")
        settings["saveManualExecutions"] = False
        settings.setdefault("callerPolicy", "workflowsFromSameOwner")


def _harden_error_handler(data: dict) -> None:
    if data.get("name") != "Error handler":
        return
    settings = data.setdefault("settings", {})
    if isinstance(settings, dict):
        settings.setdefault("executionOrder", "v1")
        settings["saveManualExecutions"] = False


def main() -> None:
    for path in sorted(WF_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        _strip_export_noise(data)
        _set_description(data)
        _harden_evolution_monitor(data)
        _harden_evolution_scheduler(data)
        _harden_health(data)
        _harden_error_handler(data)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
