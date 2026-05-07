"""Bridge between campaign event_bus topics and Slack Block Kit cards.

Subscribes once at AutomationEngine startup; every ``campaign.*`` topic
is dispatched to the matching builder in :mod:`services.slack_blocks_campaign`,
which is then sent via :meth:`AutomationEngine.notify_blocks`. Builder
failures fall back to plain :meth:`AutomationEngine.notify` so a Slack
delivery is never lost to a malformed card.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("modelforge.campaign_slack")


# Map of event_bus topic → (event_type forwarded to allow-list, dispatch fn).
def register_campaign_slack_subscriber(engine, bus) -> None:
    """Wire the campaign Slack dispatcher onto the event bus.

    ``engine`` is the live ``AutomationEngine`` instance (so we can call
    ``notify_blocks`` / ``notify``); ``bus`` is the module-level
    ``services.event_bus.bus`` singleton. Both are passed in so tests can
    swap fakes.
    """
    from services.slack_blocks_campaign import (
        campaign_started,
        campaign_experiment_complete,
        campaign_completed,
        campaign_failed,
        campaign_stopped,
    )

    async def _dispatch(evt) -> None:
        topic = evt.topic
        payload: dict[str, Any] = evt.payload or {}
        try:
            if topic == "campaign.campaign_started":
                text, blocks = campaign_started(
                    plan_id=payload.get("plan_id") or "campaign",
                    experiments=payload.get("experiments") or [],
                )
                await engine.notify_blocks(
                    text, blocks,
                    event_type="campaign_started",
                    log_message=text,
                )
                return

            if topic == "campaign.experiment_complete":
                text, blocks = campaign_experiment_complete(
                    plan_id=payload.get("plan_id") or "campaign",
                    experiment_index=int(payload.get("experiment_index") or 0),
                    total_experiments=int(payload.get("total_experiments") or 0),
                    model=payload.get("model") or "",
                    avg_score=float(payload.get("avg_score") or 0.0),
                    scores=payload.get("scores") or {},
                    stderrs=payload.get("stderrs") or {},
                    duration_seconds=payload.get("duration"),
                    eta_seconds=payload.get("eta_seconds"),
                    pace_avg_seconds=payload.get("pace_avg_seconds"),
                    completed=int(payload.get("completed") or _count_completed(payload)),
                    failed=int(payload.get("failed") or 0),
                )
                await engine.notify_blocks(
                    text, blocks,
                    event_type="campaign_experiment_complete",
                    log_message=text,
                )
                return

            if topic == "campaign.campaign_complete":
                text, blocks = campaign_completed(
                    plan_id=payload.get("plan_id") or "campaign",
                    completed=int(payload.get("completed") or 0),
                    failed=int(payload.get("failed") or 0),
                    total=int(payload.get("total") or 0),
                    total_duration_seconds=float(payload.get("total_duration_seconds") or 0.0),
                    top_results=payload.get("top_results") or [],
                )
                await engine.notify_blocks(
                    text, blocks,
                    event_type="campaign_completed",
                    log_message=text,
                )
                return

            if topic == "campaign.experiment_failed":
                text, blocks = campaign_failed(
                    plan_id=payload.get("plan_id") or "campaign",
                    experiment_index=int(payload.get("experiment_index") or 0),
                    total_experiments=int(payload.get("total_experiments") or 0),
                    model=payload.get("model") or "",
                    error=payload.get("error") or "",
                    will_continue=True,
                )
                await engine.notify_blocks(
                    text, blocks,
                    event_type="campaign_failed",
                    log_message=text,
                )
                return

            if topic == "campaign.experiment_stopped":
                text, blocks = campaign_stopped(
                    plan_id=payload.get("plan_id") or "campaign",
                    experiment_index=int(payload.get("experiment_index") or 0),
                    total_experiments=int(payload.get("total_experiments") or 0),
                )
                await engine.notify_blocks(
                    text, blocks,
                    event_type="campaign_stopped",
                    log_message=text,
                )
                return

            # Other topics (benchmark_started, benchmark_complete, model_download_*)
            # are intentionally not Slack-bound — they live in the dashboard
            # activity feed and the run_events ring buffer only.
        except Exception as exc:  # noqa: BLE001 — never let a card builder kill the bus
            logger.warning("[campaign_slack] %s dispatch failed: %s", topic, exc)
            try:
                fallback = payload.get("message") or topic
                await engine.notify(str(fallback), "🔔", event_type="campaign_started")
            except Exception:
                pass

    bus.subscribe("campaign.*", _dispatch, name="campaign_slack")
    logger.info("[campaign_slack] subscribed to campaign.* topics")


def _count_completed(payload: dict[str, Any]) -> int:
    """Best-effort completed count for a per-experiment card.

    The campaign runner doesn't snapshot completed/failed in the per-event
    payload — it does include experiment_index + total_experiments, so we
    derive: by the time experiment_complete fires, indices 0..idx are done
    (this experiment included), minus any explicit failures recorded.
    """
    idx = int(payload.get("experiment_index") or 0)
    return idx + 1  # this one just finished


def _count_failed(_payload: dict[str, Any]) -> int:
    # Per-event payload for a single experiment_complete doesn't carry the
    # campaign-wide failure count. The runner could include it later; for
    # now show 0 (the completion card is the success path).
    return 0


__all__ = ["register_campaign_slack_subscriber"]
