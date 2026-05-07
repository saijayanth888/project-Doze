"""Block Kit messages for campaign lifecycle events.

Lives next to ``slack_blocks.py`` (which handles evolution events). Same
``(text_fallback, blocks)`` tuple convention so both feed
``engine.notify_blocks``.

Four cards cover the visibility a 24-hour campaign needs:

* :func:`campaign_started` — kicked-off announcement with the model lineup.
* :func:`campaign_experiment_complete` — per-experiment scores + ETA, sent
  ~6 times across a typical baseline campaign — the message a researcher
  reads each morning.
* :func:`campaign_completed` — final summary card with top-3 ranking.
* :func:`campaign_failed` — single-experiment failure callout (campaign keeps
  going); separate from ``completed`` so it stands out in red.
"""

from __future__ import annotations

import os
from typing import Any

# Reuse the shape known to ``slack_blocks`` so anyone reading both files sees
# the same conventions.
_KNOWN_BENCHES = ("mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval")
_BENCH_LABEL = {
    "mmlu": "MMLU",
    "arc_challenge": "ARC-Chal",
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


def _short_model(model: str | None) -> str:
    if not model:
        return "?"
    return model.split("/")[-1] or model


def _fmt_score(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.3f}"


def _fmt_seconds(s: float | int | None) -> str:
    if s is None or s <= 0:
        return "—"
    s = int(s)
    h, rem = divmod(s, 3600)
    m = rem // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _score_table(scores: dict[str, float] | None, stderrs: dict[str, float] | None) -> str:
    """Markdown-formatted score table aligned with monospace font."""
    scores = scores or {}
    stderrs = stderrs or {}
    if not scores:
        return "_(no scores recorded)_"
    rows = ["```", f"{'':14} {'score':>7}  {'± stderr':>8}"]
    for bench in _KNOWN_BENCHES:
        if bench not in scores:
            continue
        sv = scores.get(bench)
        se = stderrs.get(bench)
        label = _BENCH_LABEL.get(bench, bench)[:13]
        score_s = f"{sv:.3f}" if isinstance(sv, (int, float)) else "—"
        stderr_s = f"±{se:.3f}" if isinstance(se, (int, float)) and se > 0 else ""
        rows.append(f"{label:14} {score_s:>7}  {stderr_s:>8}")
    rows.append("```")
    return "\n".join(rows)


# ── Builders ─────────────────────────────────────────────────────────


def campaign_started(
    *,
    plan_id: str,
    experiments: list[dict[str, Any]],
    estimated_duration_seconds: float | None = None,
) -> tuple[str, list[dict]]:
    text = f"🚀 Campaign started: {plan_id} · {len(experiments)} experiments"
    lines = []
    for e in experiments[:12]:
        model = _short_model(e.get("model") or e.get("base_model"))
        method = e.get("method") or "eval_only"
        lines.append(f"• `{model}` — {method}")
    if len(experiments) > 12:
        lines.append(f"… and {len(experiments) - 12} more")
    eta_line = (
        f"_est ~{_fmt_seconds(estimated_duration_seconds)}_"
        if estimated_duration_seconds
        else ""
    )
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚀 Campaign started — {plan_id}", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{len(experiments)} experiments queued*  {eta_line}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
    ]
    btn = _maybe_link("Open Dashboard", _dashboard_url("/dashboard"))
    row = _action_row(btn)
    if row:
        blocks.append(row)
    return text, blocks


def campaign_experiment_complete(
    *,
    plan_id: str,
    experiment_index: int,
    total_experiments: int,
    model: str,
    avg_score: float,
    scores: dict[str, float] | None,
    stderrs: dict[str, float] | None,
    duration_seconds: float | None,
    eta_seconds: float | None,
    pace_avg_seconds: float | None,
    completed: int,
    failed: int,
) -> tuple[str, list[dict]]:
    short = _short_model(model)
    text = (
        f"✅ Experiment {experiment_index + 1}/{total_experiments} complete · "
        f"{short} · avg {_fmt_score(avg_score)}"
    )
    pace_line = (
        f"pace ~{_fmt_seconds(pace_avg_seconds)}/exp"
        if pace_avg_seconds
        else "pace n/a"
    )
    eta_line = (
        f"ETA ~{_fmt_seconds(eta_seconds)} remaining"
        if eta_seconds
        else "ETA pending"
    )
    progress_line = (
        f"*{completed} done* · {failed} failed · "
        f"{total_experiments - completed - failed} pending · "
        f"{pace_line} · {eta_line}"
    )
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"✅ Experiment {experiment_index + 1}/{total_experiments} — {short}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Plan*\n{plan_id}"},
                {"type": "mrkdwn", "text": f"*Avg score*\n`{_fmt_score(avg_score)}`"},
                {"type": "mrkdwn", "text": f"*Duration*\n{_fmt_seconds(duration_seconds)}"},
                {"type": "mrkdwn", "text": f"*Method*\nbaseline"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _score_table(scores, stderrs)},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": progress_line}],
        },
    ]
    open_btn = _maybe_link("Open Dashboard", _dashboard_url("/dashboard"))
    camp_btn = _maybe_link("Campaign Results", _dashboard_url(f"/campaigns"))
    row = _action_row(open_btn, camp_btn)
    if row:
        blocks.append(row)
    return text, blocks


def campaign_completed(
    *,
    plan_id: str,
    completed: int,
    failed: int,
    total: int,
    total_duration_seconds: float,
    top_results: list[dict[str, Any]],
) -> tuple[str, list[dict]]:
    succeeded = [r for r in top_results if r.get("status") == "completed"]
    failures = [r for r in top_results if r.get("status") != "completed"]
    rank_lines: list[str] = []
    medals = ["🥇", "🥈", "🥉"]
    for idx, r in enumerate(succeeded[:6]):
        prefix = medals[idx] if idx < 3 else "  "
        model = _short_model(r.get("model"))
        avg = r.get("avg_score")
        rank_lines.append(f"{prefix} `{model}` — avg {_fmt_score(avg)}")
    for r in failures:
        model = _short_model(r.get("model"))
        err = (r.get("error") or "failed")[:80]
        rank_lines.append(f"❌ `{model}` — {err}")

    text = (
        f"🏁 Campaign complete: {plan_id} · {completed}/{total} succeeded "
        f"· {_fmt_seconds(total_duration_seconds)}"
    )
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🏁 Campaign complete — {plan_id}", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Succeeded*\n{completed}/{total}"},
                {"type": "mrkdwn", "text": f"*Failed*\n{failed}"},
                {"type": "mrkdwn", "text": f"*Duration*\n{_fmt_seconds(total_duration_seconds)}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Top by avg score*\n" + "\n".join(rank_lines)},
        },
    ]
    btn = _maybe_link("Open Dashboard", _dashboard_url("/dashboard"))
    camp_btn = _maybe_link("Campaign Results", _dashboard_url("/campaigns"))
    row = _action_row(btn, camp_btn)
    if row:
        blocks.append(row)
    return text, blocks


def campaign_failed(
    *,
    plan_id: str,
    experiment_index: int,
    total_experiments: int,
    model: str,
    error: str,
    will_continue: bool = True,
) -> tuple[str, list[dict]]:
    short = _short_model(model)
    text = (
        f"🔴 Experiment {experiment_index + 1}/{total_experiments} FAILED — "
        f"{short}"
    )
    cont_line = (
        f"_Campaign continuing with experiment {experiment_index + 2}/{total_experiments}_"
        if will_continue and experiment_index + 1 < total_experiments
        else "_Campaign stopping — no further experiments scheduled_"
    )
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔴 Experiment failed — {short}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Plan*\n{plan_id}"},
                {"type": "mrkdwn", "text": f"*Experiment*\n{experiment_index + 1}/{total_experiments}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Error*\n```{error[:600]}```"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": cont_line}],
        },
    ]
    btn = _maybe_link("Open Dashboard", _dashboard_url("/dashboard"))
    row = _action_row(btn)
    if row:
        blocks.append(row)
    return text, blocks


def campaign_stopped(
    *,
    plan_id: str,
    experiment_index: int,
    total_experiments: int,
) -> tuple[str, list[dict]]:
    text = f"🛑 Campaign stopped by user — {plan_id} (after exp {experiment_index + 1}/{total_experiments})"
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🛑 Campaign stopped — {plan_id}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"User clicked Stop after experiment "
                    f"{experiment_index + 1}/{total_experiments}. "
                    "Already-finished experiments are persisted in `campaign_results`."
                ),
            },
        },
    ]
    btn = _maybe_link("Open Dashboard", _dashboard_url("/dashboard"))
    row = _action_row(btn)
    if row:
        blocks.append(row)
    return text, blocks


__all__ = [
    "campaign_started",
    "campaign_experiment_complete",
    "campaign_completed",
    "campaign_failed",
    "campaign_stopped",
]
