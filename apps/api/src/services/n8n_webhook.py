"""Fire-and-forget POSTs to n8n webhooks from the evolution agent."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from config.settings import settings

logger = logging.getLogger("modelforge.n8n")


def _sign_evolution_payload(payload: dict[str, Any], secret: str) -> str:
    """HMAC-SHA256 over ``event_type|run_id|generation`` (stable across JSON shapes)."""
    gen = payload.get("generation_number", payload.get("generation", 0))
    msg = f"{payload.get('event_type', '')}|{payload.get('run_id', '')}|{gen}"
    digest = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def post_evolution_event(payload: dict[str, Any]) -> None:
    """POST ``payload`` to the configured n8n webhook (if any).

    Never raises — failures are logged at warning level so evolution
    runs are not blocked by automation glue.
    """
    url = settings.n8n_webhook_evolution_url
    if not url:
        logger.debug("N8N_WEBHOOK_EVOLUTION_URL unset — skipping n8n notify")
        return

    body_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = (settings.n8n_webhook_secret or "").strip()
    if secret:
        headers["X-Webhook-Signature"] = _sign_evolution_payload(payload, secret)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, content=body_bytes, headers=headers)
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
    total_generations: int | None = None,
    duration_seconds: float | None = None,
    champion_model_id: str | None = None,
) -> dict[str, Any]:
    """Shape expected by ``integrations/n8n/workflows/evolution-monitor``."""
    scores = child_scores or {}
    gen = int(generation)
    return {
        "event_type": event_type,
        "run_id": run_id,
        "generation_number": gen,
        "generation": gen,
        "decision": decision,
        "decision_reason": decision_reason,
        "scores": scores,
        "child_scores": scores,
        "best_score": max(scores.values()) if scores else None,
        "avg_score": sum(scores.values()) / len(scores) if scores else champion_avg,
        "champion_avg": champion_avg,
        "score": champion_avg,
        "fitness_score": champion_avg,
        "step": step,
        "error_message": error,
        "total_generations": total_generations,
        "duration_seconds": duration_seconds,
        "champion_model_id": champion_model_id,
        "model_id": champion_model_id or run_id,
    }
