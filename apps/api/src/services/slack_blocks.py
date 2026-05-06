"""Rich Slack Block Kit messages for evolution lifecycle events.

The engine's plain ``notify(text, emoji)`` API only produces ``"{emoji}
*ModelForge* — {text}"`` — fine for cron-job logs but hides the actual
information operators want at a glance: which run, which benchmarks
moved, by how much, vs the prior champion.

This module is the structured side. Each builder takes the relevant
state and returns a ``(text_fallback, blocks)`` tuple ready for
``engine.notify_blocks(...)``. Slack uses ``text`` for the
notification preview and ``blocks`` for the in-channel layout.

Set ``MODELFORGE_DASHBOARD_URL`` (e.g. ``https://forge.example.com``)
to get the "Open Dashboard" button. Without it, the action row is
omitted.
"""

from __future__ import annotations

import os
from typing import Any

# Benchmarks we track. Order matters for the score table.
_KNOWN_BENCHES = ("mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval")
_BENCH_LABEL = {
    "mmlu": "MMLU",
    "arc_challenge": "ARC-Challenge",
    "hellaswag": "HellaSwag",
    "gsm8k": "GSM8K",
    "humaneval": "HumanEval",
}


def _dashboard_url(path: str = "/dashboard") -> str | None:
    base = os.environ.get("MODELFORGE_DASHBOARD_URL", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}{path}"


def _maybe_link(label: str, url: str | None) -> dict | None:
    if not url:
        return None
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label, "emoji": True},
        "url": url,
    }


def _action_row(*buttons: dict | None) -> dict | None:
    real = [b for b in buttons if b]
    if not real:
        return None
    return {"type": "actions", "elements": real}


def _fmt_pct(delta: float) -> str:
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta * 100:.2f}%"


def _fmt_score(v: float | None) -> str:
    if v is None:
        return "  —  "
    return f"{float(v):.4f}"


def _fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "    —    "
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.4f}"


def _avg(scores: dict[str, float] | None) -> float | None:
    if not isinstance(scores, dict):
        return None
    vals = [float(v) for v in scores.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _score_table(child: dict[str, float] | None, parent: dict[str, float] | None) -> str:
    """Monospace markdown table that lines up cleanly in Slack."""
    child = child or {}
    parent = parent or {}
    keys = [k for k in _KNOWN_BENCHES if k in child] + [
        k for k in child.keys() if k not in _KNOWN_BENCHES
    ]
    if not keys:
        return "_(no scores)_"
    lines = [
        "```",
        f"{'Benchmark':<14} {'Score':>9} {'Δ vs prev':>11}",
        "─" * 36,
    ]
    for k in keys:
        new_v = child.get(k)
        old_v = parent.get(k)
        delta = (
            (float(new_v) - float(old_v))
            if isinstance(new_v, (int, float)) and isinstance(old_v, (int, float))
            else None
        )
        lines.append(
            f"{_BENCH_LABEL.get(k, k):<14} {_fmt_score(new_v):>9} {_fmt_delta(delta):>11}"
        )
    new_avg = _avg(child)
    old_avg = _avg(parent)
    if new_avg is not None:
        avg_delta = (new_avg - old_avg) if old_avg is not None else None
        lines.append("─" * 36)
        lines.append(
            f"{'AVERAGE':<14} {_fmt_score(new_avg):>9} {_fmt_delta(avg_delta):>11}"
        )
    lines.append("```")
    return "\n".join(lines)


def _config_context_line(config: dict[str, Any]) -> str:
    parts = []
    if config.get("lora_rank") is not None:
        parts.append(f"LoRA r={config['lora_rank']}")
    if config.get("lora_alpha") is not None:
        parts.append(f"α={config['lora_alpha']}")
    if config.get("learning_rate") is not None:
        parts.append(f"lr={config['learning_rate']}")
    if config.get("batch_size") is not None:
        parts.append(f"batch={config['batch_size']}")
    if config.get("max_samples") is not None:
        parts.append(f"samples={config['max_samples']}")
    return " · ".join(parts) if parts else "(no config)"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = float(seconds)
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.1f}m"
    return f"{s / 3600:.2f}h"


# ── Builders ─────────────────────────────────────────────────────────


def evolution_started(*, run_id: str, config: dict[str, Any]) -> tuple[str, list[dict]]:
    base = str(config.get("base_model") or "?")
    gens = config.get("max_generations", "?")
    text = f":rocket: Evolution started — {base} × {gens} gen — run {run_id}"
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": ":rocket: Evolution Started", "emoji": True}},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*Run*\n`{run_id}`"},
             {"type": "mrkdwn", "text": f"*Base Model*\n{base}"},
             {"type": "mrkdwn", "text": f"*Generations*\n{gens}"},
             {"type": "mrkdwn", "text": f"*Status*\n:hourglass_flowing_sand: starting"},
         ]},
        {"type": "context",
         "elements": [{"type": "mrkdwn", "text": _config_context_line(config)}]},
    ]
    actions = _action_row(_maybe_link("Open Dashboard", _dashboard_url("/dashboard")))
    if actions:
        blocks.append(actions)
    return text, blocks


def generation_promoted(
    *,
    run_id: str,
    generation: int,
    child_scores: dict[str, float],
    parent_scores: dict[str, float] | None,
    decision_reason: str | None = None,
    duration_seconds: float | None = None,
) -> tuple[str, list[dict]]:
    new_avg = _avg(child_scores) or 0.0
    text = f":trophy: Gen {generation} promoted — avg {new_avg:.3f} — run {run_id}"
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f":trophy: Champion Promoted · Gen {generation}",
                  "emoji": True}},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*Run*\n`{run_id}`"},
             {"type": "mrkdwn", "text": f"*Generation*\n{generation}"},
             {"type": "mrkdwn", "text": f"*New avg*\n*{new_avg:.4f}*"},
             {"type": "mrkdwn",
              "text": f"*Duration*\n{_fmt_duration(duration_seconds)}"},
         ]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": _score_table(child_scores, parent_scores)}},
    ]
    if decision_reason:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn", "text": f":white_check_mark: {decision_reason}"}]})
    actions = _action_row(
        _maybe_link("Lineage", _dashboard_url("/lineage")),
        _maybe_link("Adapters", _dashboard_url("/adapters")),
    )
    if actions:
        blocks.append(actions)
    return text, blocks


def generation_discarded(
    *,
    run_id: str,
    generation: int,
    child_scores: dict[str, float],
    parent_scores: dict[str, float] | None,
    decision_reason: str | None = None,
    duration_seconds: float | None = None,
) -> tuple[str, list[dict]]:
    new_avg = _avg(child_scores) or 0.0
    text = f":x: Gen {generation} discarded — avg {new_avg:.3f} — run {run_id}"
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f":x: Generation Discarded · Gen {generation}",
                  "emoji": True}},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*Run*\n`{run_id}`"},
             {"type": "mrkdwn", "text": f"*Generation*\n{generation}"},
             {"type": "mrkdwn", "text": f"*Avg*\n{new_avg:.4f}"},
             {"type": "mrkdwn",
              "text": f"*Duration*\n{_fmt_duration(duration_seconds)}"},
         ]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": _score_table(child_scores, parent_scores)}},
    ]
    if decision_reason:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn", "text": f":no_entry: {decision_reason}"}]})
    actions = _action_row(_maybe_link("Lineage", _dashboard_url("/lineage")))
    if actions:
        blocks.append(actions)
    return text, blocks


def evolution_completed(
    *,
    run_id: str,
    final_scores: dict[str, float],
    generations: int,
    base_model: str,
    duration_seconds: float | None = None,
    champion_avg: float | None = None,
) -> tuple[str, list[dict]]:
    avg_str = f"{champion_avg:.3f}" if champion_avg is not None else "?"
    text = f":white_check_mark: Run complete — {generations} gen, champion avg {avg_str} — {run_id}"
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text",
                  "text": ":white_check_mark: Evolution Complete", "emoji": True}},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*Run*\n`{run_id}`"},
             {"type": "mrkdwn", "text": f"*Base Model*\n{base_model}"},
             {"type": "mrkdwn", "text": f"*Generations*\n{generations}"},
             {"type": "mrkdwn",
              "text": f"*Wall time*\n{_fmt_duration(duration_seconds)}"},
         ]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": _score_table(final_scores, None)}},
    ]
    actions = _action_row(
        _maybe_link("Open Dashboard", _dashboard_url("/dashboard")),
        _maybe_link("Run History", _dashboard_url("/history")),
        _maybe_link("Lineage", _dashboard_url("/lineage")),
    )
    if actions:
        blocks.append(actions)
    return text, blocks


def evolution_failed(
    *,
    run_id: str,
    generation: int,
    error_type: str,
    error: str,
) -> tuple[str, list[dict]]:
    text = f":rotating_light: Run failed — {error_type} — gen {generation} — {run_id}"
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": ":rotating_light: Evolution Failed",
                  "emoji": True}},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*Run*\n`{run_id}`"},
             {"type": "mrkdwn", "text": f"*Generation*\n{generation}"},
             {"type": "mrkdwn", "text": f"*Error type*\n`{error_type}`"},
         ]},
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": f"```\n{error[:1500]}\n```"}},
    ]
    actions = _action_row(_maybe_link("View logs", _dashboard_url("/dashboard")))
    if actions:
        blocks.append(actions)
    return text, blocks


def track_promoted(
    *,
    track_id: str,
    track_name: str,
    run_id: str,
    generation: int,
    new_avg: float,
    prev_avg: float | None,
    target_benchmarks: list[str],
    full_scores: dict[str, float] | None = None,
) -> tuple[str, list[dict]]:
    text = (
        f":dart: Track '{track_name}' updated — {run_id}::gen{generation} "
        f"avg {new_avg:.3f} on {', '.join(target_benchmarks)}"
    )
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text",
                  "text": f":dart: Track Updated · {track_name}", "emoji": True}},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*Track*\n`{track_id}`"},
             {"type": "mrkdwn",
              "text": f"*Owner*\n`{run_id}::gen{generation}`"},
             {"type": "mrkdwn", "text": f"*New avg*\n*{new_avg:.4f}*"},
             {"type": "mrkdwn",
              "text": f"*Prev avg*\n{('%.4f' % prev_avg) if prev_avg is not None else '_(none)_'}"},
         ]},
        {"type": "context",
         "elements": [{"type": "mrkdwn",
                       "text": f"Target benchmarks: {', '.join(target_benchmarks)}"}]},
    ]
    actions = _action_row(_maybe_link("Open ForgeAgent", _dashboard_url("/forge")))
    if actions:
        blocks.append(actions)
    return text, blocks


__all__ = [
    "evolution_completed",
    "evolution_failed",
    "evolution_started",
    "generation_discarded",
    "generation_promoted",
    "track_promoted",
]
