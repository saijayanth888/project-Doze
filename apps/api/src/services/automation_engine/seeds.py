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
    # ── Sunday trading-track rebuild workflows (6 tracks, all disabled by default)
    #
    # Staggered 90 min apart so they don't all hammer the GPU simultaneously.
    # Each workflow: dataset.build_trading → evolution.start (gated on ok) →
    # notify.slack. Enable per-track explicitly via the dashboard once data
    # accumulates to N_MIN (see Section D of the pipeline spec).
    #
    # Cron expressions use POSIX convention (0=Sun); engine.py translates.
    # ──────────────────────────────────────────────────────────────────────────
    {
        "name": "Weekly trading-reflector rebuild",
        "description": (
            "Sunday 04:00 UTC — build the reflector dataset (closed stock trades) "
            "then evolve. DISABLED: waiting for first closed stock trade. "
            "Enable once N_MIN=100 records accumulate via the dashboard."
        ),
        "kind": "system",
        "enabled": False,  # Waiting for first closed stock trade — enable once N_MIN=100 records accumulate
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 4 * * 0"},  # Sunday 04:00 UTC
        "condition": None,
        "actions": [
            {
                "kind": "dataset.build_trading",
                "config": {"track_id": "trading-reflector"},
            },
            {
                "kind": "evolution.start",
                "config": {
                    "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                    "max_generations": 3, "max_samples": 500,
                    "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                    "track_id": "trading-reflector",
                    "eval_set_path": "{dataset.build_trading.test_set_path}",
                },
                "condition": {"last_action_status": "ok"},
            },
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Weekly trading-reflector rebuild: {dataset.build_trading.records_count} records. Run: {evolution.start.run_id}",
                    "emoji": "📊",
                    "event_type": "trading_rebuild",
                },
            },
        ],
    },
    {
        "name": "Weekly trading-bull rebuild",
        "description": (
            "Sunday 05:30 UTC — build the bull-analyst dataset and evolve. "
            "Staggered +90 min from reflector. Disabled until N_MIN=100 "
            "stock-only records pass the crypto-term blocklist."
        ),
        "kind": "system",
        "enabled": False,
        "trigger_type": "cron",
        "trigger_config": {"cron": "30 5 * * 0"},  # Sunday 05:30 UTC
        "condition": None,
        "actions": [
            {
                "kind": "dataset.build_trading",
                "config": {"track_id": "trading-bull"},
            },
            {
                "kind": "evolution.start",
                "config": {
                    "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                    "max_generations": 3, "max_samples": 500,
                    "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                    "track_id": "trading-bull",
                    "eval_set_path": "{dataset.build_trading.test_set_path}",
                },
                "condition": {"last_action_status": "ok"},
            },
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Weekly trading-bull rebuild: {dataset.build_trading.records_count} records. Run: {evolution.start.run_id}",
                    "emoji": "📊",
                    "event_type": "trading_rebuild",
                },
            },
        ],
    },
    {
        "name": "Weekly trading-bear rebuild",
        "description": (
            "Sunday 07:00 UTC — build the bear-analyst dataset and evolve. "
            "Staggered +90 min from bull. Disabled until N_MIN=100 "
            "stock-only records pass the crypto-term blocklist."
        ),
        "kind": "system",
        "enabled": False,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 7 * * 0"},  # Sunday 07:00 UTC
        "condition": None,
        "actions": [
            {
                "kind": "dataset.build_trading",
                "config": {"track_id": "trading-bear"},
            },
            {
                "kind": "evolution.start",
                "config": {
                    "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                    "max_generations": 3, "max_samples": 500,
                    "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                    "track_id": "trading-bear",
                    "eval_set_path": "{dataset.build_trading.test_set_path}",
                },
                "condition": {"last_action_status": "ok"},
            },
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Weekly trading-bear rebuild: {dataset.build_trading.records_count} records. Run: {evolution.start.run_id}",
                    "emoji": "📊",
                    "event_type": "trading_rebuild",
                },
            },
        ],
    },
    {
        "name": "Weekly trading-arbiter rebuild",
        "description": (
            "Sunday 08:30 UTC — build the arbiter dataset and evolve. "
            "Staggered +90 min from bear. Disabled until N_MIN=100 records "
            "(crypto arbiter rows may pass the blocklist — arbiter uses outcome/rationale prose)."
        ),
        "kind": "system",
        "enabled": False,
        "trigger_type": "cron",
        "trigger_config": {"cron": "30 8 * * 0"},  # Sunday 08:30 UTC
        "condition": None,
        "actions": [
            {
                "kind": "dataset.build_trading",
                "config": {"track_id": "trading-arbiter"},
            },
            {
                "kind": "evolution.start",
                "config": {
                    "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                    "max_generations": 3, "max_samples": 500,
                    "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                    "track_id": "trading-arbiter",
                    "eval_set_path": "{dataset.build_trading.test_set_path}",
                },
                "condition": {"last_action_status": "ok"},
            },
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Weekly trading-arbiter rebuild: {dataset.build_trading.records_count} records. Run: {evolution.start.run_id}",
                    "emoji": "📊",
                    "event_type": "trading_rebuild",
                },
            },
        ],
    },
    {
        "name": "Weekly trading-regime-tagger rebuild",
        "description": (
            "Sunday 10:00 UTC — build the regime-tagger dataset and evolve. "
            "Staggered +90 min from arbiter. N_MIN=40 (smaller — 7-class JSON classifier). "
            "Disabled until sufficient regime-tagger records accumulate."
        ),
        "kind": "system",
        "enabled": False,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 10 * * 0"},  # Sunday 10:00 UTC
        "condition": None,
        "actions": [
            {
                "kind": "dataset.build_trading",
                "config": {"track_id": "trading-regime-tagger"},
            },
            {
                "kind": "evolution.start",
                "config": {
                    "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                    "max_generations": 3, "max_samples": 500,
                    "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                    "track_id": "trading-regime-tagger",
                    "eval_set_path": "{dataset.build_trading.test_set_path}",
                },
                "condition": {"last_action_status": "ok"},
            },
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Weekly trading-regime-tagger rebuild: {dataset.build_trading.records_count} records. Run: {evolution.start.run_id}",
                    "emoji": "📊",
                    "event_type": "trading_rebuild",
                },
            },
        ],
    },
    {
        "name": "Weekly trading-indicator-selector rebuild",
        "description": (
            "Sunday 11:30 UTC — build the indicator-selector dataset and evolve. "
            "Staggered +90 min from regime-tagger. N_MIN=40. "
            "Requires SHARK_ENABLE_INDICATOR_SELECTOR=1 in shark phases AND "
            "N_MIN=40 real indicator_selector agent calls to accumulate (2-4 days "
            "of live Shark operation once the env var is set). Disabled until then."
        ),
        "kind": "system",
        "enabled": False,  # Requires SHARK_ENABLE_INDICATOR_SELECTOR=1 AND N_MIN=40 records
        "trigger_type": "cron",
        "trigger_config": {"cron": "30 11 * * 0"},  # Sunday 11:30 UTC
        "condition": None,
        "actions": [
            {
                "kind": "dataset.build_trading",
                "config": {"track_id": "trading-indicator-selector"},
            },
            {
                "kind": "evolution.start",
                "config": {
                    "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                    "max_generations": 3, "max_samples": 500,
                    "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                    "track_id": "trading-indicator-selector",
                    "eval_set_path": "{dataset.build_trading.test_set_path}",
                },
                "condition": {"last_action_status": "ok"},
            },
            {
                "kind": "notify.slack",
                "config": {
                    "message": "Weekly trading-indicator-selector rebuild: {dataset.build_trading.records_count} records. Run: {evolution.start.run_id}",
                    "emoji": "📊",
                    "event_type": "trading_rebuild",
                },
            },
        ],
    },
    # ── Trading eval failure alert (enabled by default; fires when eval
    #     infrastructure returns zero/negative scores, indicating stubs are
    #     active or the eval pipeline is broken). See runner.py. ─────────
    {
        "name": "Trading Eval Failure Alert",
        "description": (
            "Fires on track.eval_failed — emitted when a trading track's eval scores "
            "are zero or negative, indicating broken eval infrastructure (stubs active, "
            "judge not wired, or insufficient data). Enabled by default so operators "
            "are alerted immediately rather than silently swallowing zero-score runs."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "event",
        "trigger_config": {"pattern": "track.eval_failed"},
        "condition": None,
        "actions": [
            {
                "kind": "notify.slack",
                "config": {
                    "message": (
                        "Trading eval failure: track={track_id} run={run_id} "
                        "gen={generation} avg={new_avg} reason={reason}"
                    ),
                    "emoji": "🚨",
                    "event_type": "track_eval_failed",
                },
            },
        ],
    },
]


__all__ = ["DEFAULT_WORKFLOWS"]
