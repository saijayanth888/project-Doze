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


async def _post_json(url: str | None, payload: dict[str, Any]) -> None:
    """POST JSON to ``url`` with optional HMAC signature; never raises."""
    if not url:
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


async def post_evolution_event(payload: dict[str, Any]) -> None:
    """POST ``payload`` to the configured n8n webhook (if any).

    Never raises — failures are logged at warning level so evolution
    runs are not blocked by automation glue.
    """
    url = settings.n8n_webhook_evolution_url
    if not url:
        logger.debug("N8N_WEBHOOK_EVOLUTION_URL unset — skipping n8n notify")
        return
    await _post_json(url, payload)


async def emit_dataset_uploaded(dataset_id: str, name: str, samples: int) -> None:
    """Notify n8n after a custom dataset is uploaded."""
    url = settings.n8n_webhook_dataset_url or settings.n8n_webhook_evolution_url
    await _post_json(
        url,
        {
            "event_type": "dataset-uploaded",
            "dataset_id": dataset_id,
            "name": name,
            "samples": samples,
        },
    )


async def emit_adapter_rollback(from_adapter: str, to_adapter: str, reason: str) -> None:
    url = settings.n8n_webhook_adapter_url or settings.n8n_webhook_evolution_url
    await _post_json(
        url,
        {
            "event_type": "adapter-rollback",
            "from": from_adapter,
            "to": to_adapter,
            "reason": reason,
        },
    )


async def emit_adapter_deleted(adapter_id: str, reason: str = "") -> None:
    url = settings.n8n_webhook_adapter_url or settings.n8n_webhook_evolution_url
    await _post_json(
        url,
        {
            "event_type": "adapter-deleted",
            "adapter_id": adapter_id,
            "reason": reason,
        },
    )


async def emit_evolution_complete(run_id: str, summary: dict[str, Any]) -> None:
    """Dedicated regression-guard / completion webhook (falls back to evolution URL)."""
    url = settings.n8n_webhook_evolution_complete_url or settings.n8n_webhook_evolution_url
    payload = {"event_type": "evolution-complete", "run_id": run_id, **summary}
    await _post_json(url, payload)


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
    weak_categories: list[str] | None = None,
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
        "weak_categories": weak_categories or [],
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
