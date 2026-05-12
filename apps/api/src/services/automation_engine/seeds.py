"""Seeded workflows shipped on first boot.

These re-implement the legacy 6 default jobs (evolution scheduler, drift,
health, daily/weekly report, cleanup) using the new trigger + actions
model. They land in the DB the first time the engine starts; subsequent
boots find them and reuse the row.

`kind: "system"` flags them as un-deletable in the UI; users can still
disable, retime, or rewire actions.
"""

from __future__ import annotations

from typing import Any

DEFAULT_WORKFLOWS: list[dict[str, Any]] = [
    {
        "name": "Nightly Evolution",
        "description": "Kick off a small Llama 3.2 3B run every night at 02:00. Off by default.",
        "kind": "system",
        "enabled": False,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 2 * * *"},
        "condition": None,
        "actions": [
            {
                "kind": "evolution.start",
                "config": {
                    "base_model": "meta-llama/Llama-3.2-3B-Instruct",
                    "max_generations": 2,
                    "max_samples": 1000,
                    "lora_rank": 16,
                    "batch_size": 2,
                    "learning_rate": 0.0002,
                },
            },
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Nightly evolution kicked off — run {evolution.start.run_id}",
                    "emoji": "🚀",
                    "event_type": "evolution_started",
                },
            },
        ],
    },
    {
        "name": "Drift Detection",
        "description": "Every 6 hours, compare the latest two generations and notify Slack if any benchmark dropped > 5%.",
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 */6 * * *"},
        "condition": None,
        "actions": [
            {"kind": "drift.check", "config": {"threshold_pct": 5.0}},
            {
                "kind": "notify.slack",
                # Per-action condition: only fire when drift.check produced
                # at least one drift entry. `last.drifts` is the previous
                # action's `output.drifts` list.
                "condition": {"!=": [{"var": "last.drifts.0.benchmark"}, None]},
                "config": {
                    "message": "⚠️ Drift detected on {last.drifts.0.benchmark} (Δ {last.drifts.0.delta_pct}%) — see dashboard.",
                    "emoji": "⚠️",
                    "event_type": "drift_detected",
                },
            },
        ],
    },
    {
        "name": "Health Monitor",
        "description": "Ping postgres / redis / ollama every 15 minutes; notify Slack on failure.",
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "*/15 * * * *"},
        "condition": None,
        "actions": [
            {"kind": "health.check", "config": {}},
            {
                "kind": "notify.slack",
                # Per-action condition: notify only when health.check found
                # something failing.
                "condition": {"!=": [{"var": "last.failed.0"}, None]},
                "config": {
                    "message": "🔴 Service degraded: {last.failed}",
                    "emoji": "🔴",
                    "event_type": "health_check",
                },
            },
        ],
    },
    {
        "name": "Daily Report",
        "description": "Daily 08:00 Slack summary of the current champion.",
        "kind": "system",
        "enabled": False,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 8 * * *"},
        "condition": None,
        "actions": [
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Daily Report — see /dashboard for the latest champion + score trends.",
                    "emoji": "📊",
                    "event_type": "daily_report",
                },
            },
        ],
    },
    {
        "name": "Weekly Summary",
        "description": "Sunday 09:00 — weekly run summary.",
        "kind": "system",
        "enabled": False,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 9 * * 0"},
        "condition": None,
        "actions": [
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Weekly Summary — see /history for last 7 days of runs.",
                    "emoji": "📈",
                    "event_type": "weekly_summary",
                },
            },
        ],
    },
    {
        "name": "Auto Cleanup",
        "description": "Sunday 03:00 — delete adapter dirs older than the configured keep-days.",
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 3 * * 0"},
        "condition": None,
        "actions": [
            {"kind": "cleanup.adapters", "config": {"keep_days": 7}},
        ],
    },
    {
        "name": "System Metrics Post",
        "description": (
            "Top-of-the-hour CPU / DRAM / GPU / disk / active-campaign snapshot to "
            "Slack — phone-readable health feed for operators away from the dashboard."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 * * * *"},
        "condition": None,
        "actions": [
            {
                "kind": "system.metrics",
                "config": {
                    "include_gpu": True,
                    "include_disk": True,
                    "include_campaign": True,
                    "event_type": "system_metrics",
                },
            },
        ],
    },
    # ── Trading-bot → Ollama bridge (enabled-by-default; required for the
    #     full evolution → inference loop). Fires on every track.promoted
    #     event whose track_id starts with "trading-". ───────────────────
    {
        "name": "Publish Promoted Adapter to Ollama",
        "description": (
            "On every track.promoted for a trading-* track, push the new "
            "adapter into the host Ollama as `<base>-<role>-v<date>` and "
            "swing the `<base>-<role>-current` alias to point at it. This "
            "is the only path that closes the trading-bot → model-forge → "
            "Ollama loop -- leave it on unless you're explicitly testing."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "event",
        "trigger_config": {"pattern": "track.promoted"},
        "condition": {"startswith": [{"var": "track_id"}, "trading-"]},
        "actions": [
            {
                "kind": "adapter.publish_ollama",
                "config": {
                    "base_model": "qwen3:30b",
                    "model_name_pattern": "{base_model}-{role}-v{date}",
                    "alias_pattern": "{base_model}-{role}-current",
                    "quantization": "q4_k_m",
                },
            },
            # Mirror to private HF Hub as a durable, off-host backup.
            # Runs after the local Ollama push so a network outage on HF
            # doesn't block the zero-network publish; HF skip is silent.
            {
                "kind": "adapter.publish_huggingface",
                "config": {
                    "repo_id": "Saijayanyh532ai/dgx-trader-adapters",
                    "revision_pattern": "{track_id}-v{date}",
                    "keep_last_n": 8,
                    "include_gguf": True,
                    "include_safetensors": True,
                },
            },
            {
                "kind": "notify.slack",
                # Only ping when publish actually produced a model name --
                # skipped/error steps already record themselves on the
                # workflow run row.
                "condition": {"!=": [{"var": "last.model_name"}, None]},
                "config": {
                    "message": "Adapter published: {last.model_name} (alias {last.alias})",
                    "emoji": "📦",
                    "event_type": "adapter_published",
                },
            },
        ],
    },
    # ── Event-driven examples (off by default — show users the shape) ──
    {
        "name": "Champion-Promoted Slack Ping",
        "description": "Example event-driven workflow — fires whenever a generation gets promoted.",
        "kind": "system",
        "enabled": False,
        "trigger_type": "event",
        "trigger_config": {"pattern": "champion.promoted"},
        "condition": None,
        "actions": [
            {
                "kind": "notify.slack",
                "config": {
                    "message": "🏆 New champion — gen {generation} avg {child_avg}",
                    "emoji": "🏆",
                    "event_type": "champion_promoted",
                },
            },
        ],
    },
]


__all__ = ["DEFAULT_WORKFLOWS"]
