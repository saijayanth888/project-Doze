"""Fire-and-forget POSTs to n8n webhooks from the evolution agent."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger("modelforge.n8n")


async def post_evolution_event(payload: dict[str, Any]) -> None:
    """POST ``payload`` to the configured n8n webhook (if any).

    Never raises — failures are logged at warning level so evolution
    runs are not blocked by automation glue.
    """
    url = settings.n8n_webhook_evolution_url
    if not url:
        logger.debug("N8N_WEBHOOK_EVOLUTION_URL unset — skipping n8n notify")
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("n8n webhook POST failed (%s): %s", url, exc)


def build_evolution_payload(
    *,
    event_type: str,
    run_id: str,
    generation: int,
    decision: str | None = None,
    decision_reason: str | None = None,
    child_scores: dict[str, float] | None = None,
    champion_avg: float | None = None,
    step: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Shape expected by ``integrations/n8n/workflows/evolution-monitor``."""
    scores = child_scores or {}
    return {
        "event_type": event_type,
        "run_id": run_id,
        "generation_number": generation,
        "generation": generation,
        "decision": decision,
        "decision_reason": decision_reason,
        "scores": scores,
        "best_score": max(scores.values()) if scores else None,
        "avg_score": sum(scores.values()) / len(scores) if scores else champion_avg,
        "champion_avg": champion_avg,
        "step": step,
        "error_message": error,
    }
