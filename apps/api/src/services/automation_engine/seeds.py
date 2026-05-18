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


def _weekly_trading_rebuild_actions(track_id: str, n_min_train: int) -> list[dict[str, Any]]:
    """Return the 5-step action list for a Sunday trading-track rebuild workflow.

    The 5 steps give FULL Slack coverage on every training event — no silent
    paths, no broken-template messages:

      0. notify.slack (unconditional)         — 🟦 Rebuild starting: <track>
      1. dataset.build_trading                — runs ingest + curate; N_MIN-gated
      2. evolution.start (cond ok)            — only fires when curator passed
      3. notify.slack (cond ok)               — ✅ Training fired: run <id>
      4. notify.slack (cond skipped)          — ⏳ Insufficient data: <records>/<N_MIN>

    The condition-chain semantics: ``last_action_status`` checks the prior step.
    When step 2 is skipped, step 3 (cond=ok) is skipped too, then step 4
    (cond=skipped) fires. When step 2 succeeds, step 3 fires (cond=ok), then
    step 4 (cond=skipped) is skipped. Both branches always reach exactly ONE
    Slack ping at the end.
    """
    return [
        {
            "kind": "notify.slack",
            "config": {
                "message": f"🟦 Sunday rebuild starting: {track_id}",
                "emoji": "🟦",
                "event_type": "trading_rebuild_started",
            },
        },
        {
            "kind": "dataset.build_trading",
            "config": {"track_id": track_id},
        },
        {
            "kind": "evolution.start",
            "config": {
                "base_model": "NousResearch/Hermes-3-Llama-3.1-8B",
                "max_generations": 3, "max_samples": 500,
                "lora_rank": 16, "batch_size": 2, "learning_rate": 0.0002,
                "track_id": track_id,
                "eval_set_path": "{dataset.build_trading.test_set_path}",
            },
            "condition": {"last_action_status": "ok"},
        },
        {
            "kind": "notify.slack",
            "condition": {"last_action_status": "ok"},
            "config": {
                "message": (
                    f"✅ {track_id} training fired — "
                    "{dataset.build_trading.records_count} records cleared N_MIN gate, "
                    "evolution run {evolution.start.run_id} started"
                ),
                "emoji": "✅",
                "event_type": "trading_rebuild_training_fired",
            },
        },
        {
            "kind": "notify.slack",
            "condition": {"last_action_status": "skipped"},
            "config": {
                "message": (
                    f"⏳ {track_id} gate: insufficient data "
                    "({dataset.build_trading.records_count} records < N_MIN=" + str(n_min_train) + "). "
                    "No training fired. Workflow will retry next Sunday."
                ),
                "emoji": "⏳",
                "event_type": "trading_rebuild_insufficient_data",
            },
        },
    ]


# Per-track N_MIN_TRAIN thresholds (mirrors modelforge_curate.py::N_MIN_TRAIN).
# Used to build accurate Slack messages on the insufficient-data branch.
_N_MIN_TRAIN_PER_TRACK = {
    "trading-reflector": 100,
    "trading-bull": 100,
    "trading-bear": 100,
    "trading-arbiter": 100,
    "trading-regime-tagger": 40,
    "trading-indicator-selector": 40,
}


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
    # ── Sunday trading-track rebuild workflows (6 tracks, all ENABLED by default)
    #
    # Fully cron-automated. Each workflow self-gates on data via the
    # BuildTradingDataset action's N_MIN check. Insufficient data → fail-loud
    # Slack alert via step 4; data ready → training fires via step 2 and
    # success Slack via step 3.
    #
    # Staggered 90 min apart so they don't all hammer the GPU simultaneously.
    # Each workflow has 5 actions (see ``_weekly_trading_rebuild_actions``):
    #   0. notify.slack (starting)
    #   1. dataset.build_trading
    #   2. evolution.start (cond ok)
    #   3. notify.slack (cond ok — training fired)
    #   4. notify.slack (cond skipped — insufficient data)
    #
    # This shape gives FULL Slack coverage on every Sunday run regardless of
    # outcome — no silent paths, no broken-template messages.
    #
    # Cron expressions use POSIX convention (0=Sun); engine.py translates.
    # ──────────────────────────────────────────────────────────────────────────
    {
        "name": "Weekly trading-reflector rebuild",
        "description": (
            "Sunday 04:00 UTC — build the reflector dataset (closed stock trades) "
            "then evolve. Self-gates on N_MIN=100 closed stock trades; fail-loud "
            "Slack alert weekly until accumulation completes."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 4 * * 0"},  # Sunday 04:00 UTC
        "condition": None,
        "actions": _weekly_trading_rebuild_actions(
            "trading-reflector", _N_MIN_TRAIN_PER_TRACK["trading-reflector"],
        ),
    },
    {
        "name": "Weekly trading-bull rebuild",
        "description": (
            "Sunday 05:30 UTC — build the bull-analyst dataset and evolve. "
            "Staggered +90 min from reflector. Self-gates on N_MIN=100 "
            "stock-only records (crypto-term blocklist filters cross-asset prose)."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "30 5 * * 0"},  # Sunday 05:30 UTC
        "condition": None,
        "actions": _weekly_trading_rebuild_actions(
            "trading-bull", _N_MIN_TRAIN_PER_TRACK["trading-bull"],
        ),
    },
    {
        "name": "Weekly trading-bear rebuild",
        "description": (
            "Sunday 07:00 UTC — build the bear-analyst dataset and evolve. "
            "Staggered +90 min from bull. Self-gates on N_MIN=100 stock-only records."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 7 * * 0"},  # Sunday 07:00 UTC
        "condition": None,
        "actions": _weekly_trading_rebuild_actions(
            "trading-bear", _N_MIN_TRAIN_PER_TRACK["trading-bear"],
        ),
    },
    {
        "name": "Weekly trading-arbiter rebuild",
        "description": (
            "Sunday 08:30 UTC — build the arbiter dataset and evolve. "
            "Staggered +90 min from bear. Self-gates on N_MIN=100 records."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "30 8 * * 0"},  # Sunday 08:30 UTC
        "condition": None,
        "actions": _weekly_trading_rebuild_actions(
            "trading-arbiter", _N_MIN_TRAIN_PER_TRACK["trading-arbiter"],
        ),
    },
    {
        "name": "Weekly trading-regime-tagger rebuild",
        "description": (
            "Sunday 10:00 UTC — build the regime-tagger dataset and evolve. "
            "Staggered +90 min from arbiter. Self-gates on N_MIN=40 records "
            "(smaller — 7-class JSON classifier)."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "0 10 * * 0"},  # Sunday 10:00 UTC
        "condition": None,
        "actions": _weekly_trading_rebuild_actions(
            "trading-regime-tagger", _N_MIN_TRAIN_PER_TRACK["trading-regime-tagger"],
        ),
    },
    {
        "name": "Weekly trading-indicator-selector rebuild",
        "description": (
            "Sunday 11:30 UTC — build the indicator-selector dataset and evolve. "
            "Staggered +90 min from regime-tagger. Self-gates on N_MIN=40 records. "
            "Requires SHARK_ENABLE_INDICATOR_SELECTOR=1 in shark phases "
            "(set in trading-bot/.env)."
        ),
        "kind": "system",
        "enabled": True,
        "trigger_type": "cron",
        "trigger_config": {"cron": "30 11 * * 0"},  # Sunday 11:30 UTC
        "condition": None,
        "actions": _weekly_trading_rebuild_actions(
            "trading-indicator-selector", _N_MIN_TRAIN_PER_TRACK["trading-indicator-selector"],
        ),
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
